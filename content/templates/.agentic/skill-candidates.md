# Skill Candidates

Recurring workflow friction detected across sessions. Each entry represents a
domain that has accumulated enough occurrences to warrant considering a new
skill. Detection signal: `tool_failure_workaround` events (by `domain_tag`) and
`.agentic/learnings.md` entries (by `Domain`), threshold >= 3 across sessions.

Classification rules and routing taxonomy are in
`content/commands/skill-candidates.md`. The detector is in
`hooks/lib/skill-candidate-detector.js`.

## Entry format

Each candidate uses this exact format. The `## <domain>` heading is the unique
key (no separate id field). `Status` is set to `open` by the detector; a human
edits it to `dismissed` to suppress future session-start notices.

```markdown
## <domain>
**Count:** <lifetime occurrence count>
**Suggested artifact:** command | named-agent | preset | lint-rule
**First seen:** YYYY-MM-DD
**Last seen:** YYYY-MM-DD
**Status:** open
**Example:** "<data.note from the triggering event>"
```

Do not hand-edit `Count`, `First seen`, or `Last seen` - they are maintained by
the detector. To dismiss a candidate, change `**Status:** open` to
`**Status:** dismissed`.

## Candidates

<!-- Entries appended by Stop hook (runSkillCandidateScan). -->
