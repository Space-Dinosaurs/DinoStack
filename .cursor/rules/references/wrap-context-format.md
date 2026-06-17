# Wrap context.md Format (shared normative reference)

> Consumers: `content/commands/wrap.md` (Part A) and `content/commands/wrap-deferred.md`. Both CITE this file for the pinned header prefix, the `context.md` rolling-session-label merge algorithm, the `.agentic/.last-wrap` write contract, and the spillover-drain procedure. This is the single normative home for those four contracts so that the interactive `/wrap` and the non-interactive `/wrap-deferred` write byte-identical `context.md` output. Edit the algorithm here, not in either consumer.

This is a prose reference. It restates - verbatim - the shared `context.md` formatting contract that previously lived inline in `content/commands/wrap.md` Part A. The extraction is behavior-preserving: a golden-file byte-identity test pins `/wrap` Part A output across the extraction.

## Pinned header prefix (NORMATIVE)

Exactly one byte-exact prefix is the contract between writer and matcher:

    # Session Context\n*Written by /wrap

This is what the `/wrap`-coexistence `existing.startsWith('# Session Context\n*Written by /wrap')` check in `hooks/stop-context.js` (the "Append/replace session activity on /wrap-authored files" step) and the equivalent `startsWith` check in `.opencode/plugins/session-context.ts` test, and what every `/wrap` Output-1 / merge write must emit as its first two lines. (Referenced by behavior, not line number, so the citation does not rot as those files change.) The on-disk header date is a UTC calendar date (`date -u +%Y-%m-%d`); the header STRING does NOT contain the "UTC" literal - it stays `*Written by /wrap on YYYY-MM-DD. ...` exactly as the Output-1 template reads. The matcher only tests the pinned prefix (which stops before the date), so the date format and the absence of the "UTC" literal are both compatible. The Part A merge rule (the "(merged context)" header rewrite) appends after the date and is outside the pinned prefix - it stays. The rolling-session-label merge (below) is preserved unchanged.

"Second line" means the literal second line of the file. A `/wrap`-produced file always starts with `# Session Context` on line 1 and `*Written by /wrap on ...` on line 2.

## `.agentic/.last-wrap` write contract (NORMATIVE)

A single line containing the `session_id` of the session whose `/wrap` (sync, background enrichment, or `/wrap-deferred`) last successfully wrote `context.md`. Atomic write (tmp + rename). This sentinel fully replaces any header-date parsing - no site parses the `context.md` header date to decide "was this session wrapped." Consumers: (a) the Stop hook's marker-staging suppression (do not stage a marker if the current `session_id` equals `.last-wrap`), and (b) the OpenCode plugin's equivalent suppression. It is written ONLY after a successful Part A `context.md` write - never staged early (writing it during marker-staging would suppress that very session's own recovery marker). Note: a same-session `done` tombstone stamped `wrapped_at` ALSO suppresses `stagePending` (covering the case where `.last-wrap` has rolled to a different session), so `.last-wrap` is not the sole staging-suppression mechanism - the retained tombstone is the durable backstop when `.last-wrap` no longer names this session.

The `.last-wrap` write is performed inside the same narrow lock window as the `context.md` write: it is the last write before the lock is released (after the merged `context.md` write, before lock release). The interactive `/wrap` releases the lock itself (via the `agentic-wrap-release-lock` helper); on the headless `/wrap-deferred` path the lock is cleared out-of-band by the daemon's stale-lock backstop, since that child has no Bash — so `.last-wrap` is the child's last write.

## Spillover-drain procedure (NORMATIVE, 3-step rename-first)

Run this as the first action inside the locked Part A window, before the rolling-session-label merge. The three steps; rename-first prevents loss of a record a hook appended just before the lock was observed:

1. `rename(.agentic/.stop-deferred-activity.jsonl -> .agentic/.stop-deferred-activity.jsonl.draining.<pid>)`. Atomic. Any hook append after this rename creates a fresh `.stop-deferred-activity.jsonl` belonging to the next drain - not lost.
2. Read the renamed copy's records and fold them into the `context.md` activity block (each record carries its own `session_id`, preserving cross-session provenance; the block header reflects the enrichment session).
3. `unlink(.agentic/.stop-deferred-activity.jsonl.draining.<pid>)`.

The spillover log record schema (`.agentic/.stop-deferred-activity.jsonl`, append-only JSONL, one record per Stop-hook / OpenCode-idle invocation that found `wrap.lock` held and skipped its `context.md` write):

    {"schema_version": 1, "ts": "<ISO8601 UTC>", "session_id": "<uuid>", "recent_focus": ["<msg>"], "paths_referenced": ["<path>"], "uncommitted": ["<status code + path>"], "tools_used": ["<tool>"]}

A crash between the rename and the unlink can leave a `.agentic/.stop-deferred-activity.jsonl.draining.*` temp file. A session-start drain-temp sweep (`rm -f .agentic/.stop-deferred-activity.jsonl.draining.*`, fail-open) cleans it.

## context.md rolling-session-label merge algorithm (NORMATIVE)

The merged write always begins with the pinned header prefix above (the matcher contract); no site parses the header date.

1. Read the file at the `context.md` output path.

2. **If the file does not exist**: write the new draft content directly to the output path. Result: "Wrote fresh context to [path] (no existing file)."

3. **If the file exists but is empty, or its second line does not begin with `*Written by /wrap`**: the existing file was written by the Stop hook or another source and cannot be meaningfully merged. Write the new draft content directly, overwriting the existing file. Result: "Wrote fresh context to [path] (replaced non-/wrap file)."

4. **If the file exists and its second line begins with `*Written by /wrap`** (i.e. it was produced by a previous `/wrap` run): proceed to the merge step below.

### Merge step

**Duplicate-claim dedup (idempotency).** Before assigning a new session label below, apply the Recent-Focus dedup rule: key the new draft by the marker's `session_id` + `staged_at`; if a draft for this same `session_id`+`staged_at` has already been folded under an existing label (a re-run of the same marker across two sessions), SKIP the append entirely - do not add a new label, do not roll the window. The rest of Part A (Part B/C/E gating, `.last-wrap` write) still proceeds. This makes a duplicate enrichment of the same marker wasteful but non-corrupting.

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

Write the merged result to disk. Result: "Merged context written to [path] (combined sessions)."
