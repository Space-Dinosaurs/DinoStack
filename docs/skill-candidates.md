<!--
Purpose: Operator-facing guide for the skill-candidate detection system.
         Explains what it is, how candidates are detected at wrap time,
         what the operator sees (session-start notices and the backlog file),
         how to use /skill-candidates, and how to act on or dismiss a candidate.

Public API: Operator-facing prose. Entry point for anyone who sees a
            SKILL-CANDIDATE notice or finds .agentic/skill-candidates.md.
            Deeper spec lives in content/commands/skill-candidates.md and
            content/commands/wrap.md §Part D.

Upstream deps: content/commands/skill-candidates.md (command spec and entry format);
               content/commands/wrap.md §Part D (detection and deep-cluster invocation);
               content/rules/conventions.md §Skill-candidate sweep at session start
               (session-start notice logic and pagination);
               hooks/lib/skill-candidate-deep-cluster.js (the cluster merge helper).

Downstream consumers: docs site root index.

Failure modes: Stale if entry format, detection threshold, or /skill-candidates
               command behavior changes. Update alongside content/commands/skill-candidates.md.

Performance: Standard.
-->

# Skill-candidate detection

DinoStack watches for recurring workflow friction across sessions. When the same
kind of manual workaround appears at least three times, it promotes the pattern
to a **skill candidate** - a suggestion that the friction is worth turning into
a reusable command, named agent, preset, or lint rule.

You do not configure this. It runs automatically at the end of every `/wrap`
call and surfaces results the next time you start a session.

## How detection works

Detection runs in two stages, both during `/wrap`:

**1. Inline LLM extraction (Part D).**
At wrap time, the conductor reflects on the session and extracts 0-5 entries
describing distinct domains where you or the conductor did repeated manual work
or hit the same friction. Each entry has a `domain` slug (e.g. `adapter-rebuild`,
`deploy-verification`), an `exampleNote` describing the concrete instance, and
an optional `suggestedArtifact` (`command | named-agent | preset | lint-rule`).

**2. Deep-cluster helper.**
The extracted array is written to a temp file and passed to
`hooks/lib/skill-candidate-deep-cluster.js`. The helper reads
`.agentic/skill-candidates.md` in the project, merges new occurrences into
existing entries by exact `domain` slug, and promotes any domain that reaches
the >= 3 occurrence threshold. Merging is additive: `Count`, `First seen`, and
`Last seen` are maintained by the helper - do not hand-edit them.

**What triggers promotion:**
A domain reaches >= 3 occurrences across sessions (from `tool_failure_workaround`
events in `.agentic/events.jsonl`, `.agentic/learnings.md` entries, and the
wrap-time LLM extraction signal): in practice the wrap-time extraction is the
active source; the `events.jsonl` path stays dormant until those events are emitted.

**Gating:**
Detection is on by default. Set `skill_candidate_detection: false` in
`.agentic/config.json` to disable it for a project. The default (key absent or
config missing) is enabled.

## What you see at session start

Each session, the conductor scans `.agentic/skill-candidates.md` for `open`
entries that have not yet been surfaced to you. For each new unsurfaced entry,
it emits a non-blocking notice before your first response:

```
SKILL-CANDIDATE: domain 'adapter-rebuild' has accumulated 4 occurrences - consider creating a skill (suggested artifact: command). Run /skill-candidates for the full backlog.
[phase: skill-candidate]
```

The notice fires once per domain per project. After that, the domain is recorded
in `.agentic/.skill-candidates-surfaced` and suppressed in future sessions. The
sweep is paginated - it reads only entries newer than the last sweep timestamp,
so it stays fast regardless of backlog size.

The notice never blocks any conductor action. It is informational only.

## The backlog file: .agentic/skill-candidates.md

All candidates live in `.agentic/skill-candidates.md` at the project root.
This file is committed in consumer projects (via a `!.agentic/skill-candidates.md`
carve-out in the scaffolding gitignore), so the backlog travels with the repo
and is visible to all team members.

Each entry uses this exact format:

```markdown
## <domain>
**Count:** <lifetime occurrence count>
**Suggested artifact:** command | named-agent | preset | lint-rule
**First seen:** YYYY-MM-DD
**Last seen:** YYYY-MM-DD
**Status:** open
**Example:** "<one sentence from the triggering session>"
```

The `## <domain>` heading is the unique key. The detector merges by exact slug
match - keep slugs lowercase-hyphenated (e.g. `adapter-rebuild`, not
`adapter_rebuild`).

Fields maintained by the detector: `Count`, `First seen`, `Last seen`.
Field you control: `Status` (`open` or `dismissed`).

## Using /skill-candidates

Run `/skill-candidates` from any session to view the full backlog:

```
/skill-candidates
```

No flags, no subcommands. It reads `.agentic/skill-candidates.md` from the
current working directory and groups entries into three buckets:

- **OPEN** - entries not yet surfaced to you this session
- **OPEN (already surfaced)** - entries that have been surfaced before but are still open
- **DISMISSED** - entries you have suppressed

If the file is absent:

```
No skill candidates detected yet.

The detector runs at the end of each `/wrap` call and writes candidates here
when a domain tag accumulates >= 3 occurrences. Check back after a few
more sessions, or verify that skill_candidate_detection is true in
.agentic/config.json.
```

Example output when candidates exist:

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

To create a skill for an open item: create a skill for the domain manually,
  or use your usual skill-authoring flow
To dismiss a candidate: edit .agentic/skill-candidates.md and change
  **Status:** open  to  **Status:** dismissed
```

## Acting on a candidate

**Create a skill.**
Create a skill for the domain manually, or use your usual skill-authoring flow.
The candidate entry in `.agentic/skill-candidates.md` includes the domain slug,
suggested artifact type, and a concrete example to guide authoring.

**Dismiss a candidate.**
Open `.agentic/skill-candidates.md` and change the entry's `**Status:**` field
from `open` to `dismissed`. The session-start notice will no longer fire for
that domain, and `/skill-candidates` will list it under DISMISSED.

Do not delete entries - the detector will re-promote them if the same friction
continues. Setting `dismissed` signals that you have decided not to build a
skill for this domain (or that the friction has been resolved another way).

## When does the file not appear?

- `skill_candidate_detection: false` in `.agentic/config.json` - detection and
  the session-start sweep are both disabled.
- Fewer than 3 occurrences for any domain across sessions - the threshold has
  not been reached.
- The `/wrap` command is never run, or `$CLAUDE_CODE_SESSION_ID` is unset at
  wrap time - the deep-cluster helper is skipped (soft no-op).
- You are in the DinoStack methodology source repo itself - `.agentic/*` is
  gitignored there by design. DinoStack is the source, not a consumer project.

## Related references

- `content/commands/skill-candidates.md` - full command spec: entry format,
  grouping logic, gating, and the intent-layer note on file commit behavior
- `content/commands/wrap.md` §Part D - the wrap-time detection flow and
  deep-cluster helper invocation
- `content/rules/conventions.md` §Skill-candidate sweep at session start -
  the session-start notice logic, surfacing rules, and pagination
- `hooks/lib/skill-candidate-deep-cluster.js` - the cluster merge and
  promotion helper
