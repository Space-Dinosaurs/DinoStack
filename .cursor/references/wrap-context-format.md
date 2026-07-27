# Wrap curated-context Format (shared normative reference)

> Consumers: `content/commands/ds-wrap.md` (Part A) and `content/commands/ds-wrap-deferred.md`. Both CITE this file for the pinned header prefix, the rolling-session-label merge algorithm, the `.agentic/wrap/last-wrap` write contract, and the spillover-drain procedure. This is the single normative home for those four contracts so that the interactive `/ds-wrap` and the non-interactive `/ds-wrap-deferred` write byte-identical output. Edit the algorithm here, not in either consumer.

This is a prose reference. It restates - verbatim - the shared formatting contract that previously lived inline in `content/commands/ds-wrap.md` Part A. The extraction is behavior-preserving: a golden-file byte-identity test pins `/ds-wrap` Part A output across the extraction.

## Output path: `.agentic/_wrap.md`, and the sentinel partition (NORMATIVE)

**The merge algorithm below is UNCHANGED. Only the file it reads and writes moved**, from `.agentic/context.md` to `.agentic/_wrap.md`. This is a path retarget, not a rewrite: `/ds-wrap`, `/ds-wrap-deferred`, and `wrap-ticket` all execute the identical normative algorithm on the new path.

`.agentic/context.md` is now a **derived rollup**, partitioned at the `\n\n---\n\n## Session Activity\n` sentinel:

| Region | Owner | Written by |
|---|---|---|
| Everything UP TO the sentinel (the header, `## Recent Focus` and its 10-slot rolling label window, `## Watch Out For`, and every other curated section) | `.agentic/_wrap.md` | `/ds-wrap` Part A, `/ds-wrap-deferred`, `wrap-ticket`, a conductor-direct context write |
| Everything FROM the sentinel onward (the activity region) | per-session shards in `.agentic/context.d/` | the Claude Stop hook, the OpenCode plugin, `bin/agentic-migrate` |

The two regions carry two DIFFERENT accumulation windows, and that is the accepted cost of the partition: 10 curated session labels before the sentinel, up to 10 session shards after it. They are disjoint. **A derived region must never own curated content** - the rollup is regenerated idempotently on every turn, and a derived file cannot hold curated narrative without destroying either the curation or the idempotence that licenses writing it without a lock.

**Do not write `.agentic/context.md` from any `/ds-wrap` path.** The next Stop turn recomposes it from `_wrap.md` plus the shard set, so a direct write is silently discarded. Write `_wrap.md`.

**Migration is automatic and one-time.** The first rollup regeneration in a project where `_wrap.md` does not yet exist seeds it from any pre-existing `context.md` whose second line matches the pinned prefix below, keeping **lines 1-2 byte-exact** - because step 3 of the merge algorithm overwrites any file whose second line does not begin `*Written by /ds-wrap`, a seed that altered those two lines would be discarded by the very next `/ds-wrap` and the 10-slot window would be lost. A `context.md` that is NOT `/ds-wrap`-authored is preserved as `.agentic/_foreign.md` and never seeds the curated file. Machine-derived blocks (activity regions, capture-gap and identity nudges) are stripped from the seed; content that merely QUOTES the sentinel is preserved verbatim.

The end-to-end rationale - 13 writer sites, no mutual exclusion between them, and an immortal lock that silently discarded 49 writes across 6 sessions in 10.3 hours - lives in `content/references/conductor-operating-rules.md` under "`.agentic/context.md` writer contract".

## Pinned header prefix (NORMATIVE)

Exactly one byte-exact prefix is the contract between writer and matcher:

    # Session Context\n*Written by /ds-wrap

This is what the **second-line** discriminator tests - in step 3 of the merge algorithm below, and in the one-time migration that seeds `_wrap.md` from a pre-existing `context.md` (`hooks/lib/context-rollup.js` `isWrapAuthored`, and the equivalent check in `.opencode/plugins/session-context.ts`) - and what every `/ds-wrap` Output-1 / merge write must emit as its first two lines. (The former `existing.startsWith(...)` checks in `hooks/stop-context.js` and the OpenCode plugin, which selected a strip-and-append branch, are RETIRED along with that branch; the prefix contract itself is unchanged and is now load-bearing for migration instead.) (Referenced by behavior, not line number, so the citation does not rot as those files change.) The on-disk header date is a UTC calendar date (`date -u +%Y-%m-%d`); the header STRING does NOT contain the "UTC" literal - it stays `*Written by /ds-wrap on YYYY-MM-DD. ...` exactly as the Output-1 template reads. The matcher only tests the pinned prefix (which stops before the date), so the date format and the absence of the "UTC" literal are both compatible. The Part A merge rule (the "(merged context)" header rewrite) appends after the date and is outside the pinned prefix - it stays. The rolling-session-label merge (below) is preserved unchanged.

"Second line" means the literal second line of the file. A `/ds-wrap`-produced file always starts with `# Session Context` on line 1 and `*Written by /ds-wrap on ...` on line 2.

## `.agentic/wrap/last-wrap` write contract (NORMATIVE)

A single line containing the `session_id` of the session whose `/ds-wrap` (sync, background enrichment, or `/ds-wrap-deferred`) last successfully wrote `_wrap.md`. Atomic write (tmp + rename). This sentinel fully replaces any header-date parsing - no site parses the `_wrap.md` header date to decide "was this session wrapped." Consumers: (a) the Stop hook's marker-staging suppression (do not stage a marker if the current `session_id` equals `last-wrap`), and (b) the OpenCode plugin's equivalent suppression. It is written ONLY after a successful Part A `_wrap.md` write - never staged early (writing it during marker-staging would suppress that very session's own recovery marker). Note: a same-session `done` tombstone stamped `wrapped_at` ALSO suppresses `stagePending` (covering the case where `last-wrap` has rolled to a different session), so `last-wrap` is not the sole staging-suppression mechanism - the retained tombstone is the durable backstop when `last-wrap` no longer names this session.

The `last-wrap` write is performed inside the same narrow lock window as the `_wrap.md` write: it is the last write before the lock is released (after the merged `_wrap.md` write, before lock release). The interactive `/ds-wrap` releases the lock itself (via the `agentic-wrap-release-lock` helper); on the headless `/ds-wrap-deferred` path the lock is cleared out-of-band by the daemon's stale-lock backstop, since that child has no Bash — so `last-wrap` is the child's last write.

<!-- ACCEPTED cross-version window: during an in-place upgrade where old-code sessions use .agentic/wrap.lock and new-code sessions use .agentic/wrap/lock, two sessions may hold different lock paths concurrently. This race is bounded to a transient recency-label discrepancy in context.md (a convenience label, not committed work). It self-heals on the next clean SessionStart. No lost-update of committed work occurs; the window is accepted and documented. -->

## Spillover-drain procedure (NORMATIVE, 3-step rename-first)

Run this as the first action inside the locked Part A window, before the rolling-session-label merge. The three steps; rename-first prevents loss of a record a hook appended just before the lock was observed:

1. `rename(.agentic/wrap/deferred-activity.jsonl -> .agentic/wrap/deferred-activity.jsonl.draining.<pid>)`. Atomic. Any hook append after this rename creates a fresh `deferred-activity.jsonl` belonging to the next drain - not lost.
2. Read the renamed copy's records and fold them into `_wrap.md`'s curated `## Recent Focus` region (each record carries its own `session_id`, preserving cross-session provenance). The rename-first mechanics and the `session_id`+`staged_at` dedup are unchanged. **The destination is not:** records used to be folded into `context.md`'s derived activity block, and they now land in the curated Recent-Focus region, which means drained records are newly subject to the 10-slot rolling window that governs that region. This is the correct home for them - they are prior sessions' curated summaries, not this turn's raw activity, and the activity region is now regenerated wholesale from shards on every turn so nothing appended there would survive. Stated explicitly because "only the target file moved" understates it: the target **region** moved too.
3. `unlink(.agentic/wrap/deferred-activity.jsonl.draining.<pid>)`.

**No new spillover records are produced.** Spillover existed only because a held `wrap/lock` made a per-turn writer SKIP its `context.md` write; per-turn writers now write session-private shards and are never skipped, so nothing is deferred. The drain above is retained deliberately so records written before that change are not orphaned - including the 49 preserved from the live incident. The historical record schema (`.agentic/wrap/deferred-activity.jsonl`, append-only JSONL, one record per skipped write) is kept here for readers of an existing file:

    {"schema_version": 1, "ts": "<ISO8601 UTC>", "session_id": "<uuid>", "recent_focus": ["<msg>"], "paths_referenced": ["<path>"], "uncommitted": ["<status code + path>"], "tools_used": ["<tool>"]}

A crash between the rename and the unlink can leave a `.agentic/wrap/deferred-activity.jsonl.draining.*` temp file. A session-start drain-temp sweep (`rm -f .agentic/wrap/deferred-activity.jsonl.draining.*`, fail-open) cleans it.

## `_wrap.md` rolling-session-label merge algorithm (NORMATIVE)

The merged write always begins with the pinned header prefix above (the matcher contract); no site parses the header date.

1. Read the file at the `_wrap.md` output path (`.agentic/_wrap.md`).

2. **If the file does not exist**: write the new draft content directly to the output path. Result: "Wrote fresh context to [path] (no existing file)."

3. **If the file exists but is empty, or its second line does not begin with `*Written by /ds-wrap`**: the existing file was written by the Stop hook or another source and cannot be meaningfully merged. Write the new draft content directly, overwriting the existing file. Result: "Wrote fresh context to [path] (replaced non-/ds-wrap file)."

4. **If the file exists and its second line begins with `*Written by /ds-wrap`** (i.e. it was produced by a previous `/ds-wrap` run): proceed to the merge step below.

### Merge step

**Duplicate-claim dedup (idempotency).** Before assigning a new session label below, apply the Recent-Focus dedup rule: key the new draft by the marker's `session_id` + `staged_at`; if a draft for this same `session_id`+`staged_at` has already been folded under an existing label (a re-run of the same marker across two sessions), SKIP the append entirely - do not add a new label, do not roll the window. The rest of Part A (Part B/C/E gating, `last-wrap` write) still proceeds. This makes a duplicate enrichment of the same marker wasteful but non-corrupting.

First, check how many session labels are already present in the existing file's Recent Focus section.

- **Ten labels present (`[Session A]` through `[Session J]`)**: apply a rolling-window merge. Discard the `[Session A]` content from Recent Focus, relabel `[Session B]` as `[Session A]`, `[Session C]` as `[Session B]`, `[Session D]` as `[Session C]`, `[Session E]` as `[Session D]`, `[Session F]` as `[Session E]`, `[Session G]` as `[Session F]`, `[Session H]` as `[Session G]`, `[Session I]` as `[Session H]`, `[Session J]` as `[Session I]`, and use the new draft as `[Session J]`. For all other sections (Current Task / Next Steps, Key File Paths, Watch Out For, Tools Used), treat the full existing content as the prior session and apply the standard merge rules below.

- **Nine labels present (`[Session A]` through `[Session I]`)**: label the new draft entry `[Session J]` and append it as its own paragraph in Recent Focus. For all other sections, treat the full existing content as the prior session(s) and apply the standard merge rules below.

- **Eight labels present (`[Session A]` through `[Session H]`)**: label the new draft entry `[Session I]` and append it as its own paragraph in Recent Focus. For all other sections, treat the full existing content as the prior session(s) and apply the standard merge rules below.

- **Seven labels present (`[Session A]` through `[Session G]`)**: label the new draft entry `[Session H]` and append it as its own paragraph in Recent Focus. For all other sections, treat the full existing content as the prior session(s) and apply the standard merge rules below.

- **Six labels present (`[Session A]` through `[Session F]`)**: label the new draft entry `[Session G]` and append it as its own paragraph in Recent Focus. For all other sections, treat the full existing content as the prior session(s) and apply the standard merge rules below.

- **Five labels present (`[Session A]` through `[Session E]`)**: label the new draft entry `[Session F]` and append it as its own paragraph in Recent Focus. For all other sections, treat the full existing content as the prior session(s) and apply the standard merge rules below.

- **Four labels present (`[Session A]` through `[Session D]`)**: label the new draft entry `[Session E]` and append it as its own paragraph in Recent Focus. For all other sections, treat the full existing content as the prior session(s) and apply the standard merge rules below.

- **Three labels present (`[Session A]`, `[Session B]`, `[Session C]`)**: label the new draft entry `[Session D]` and append it as its own paragraph in Recent Focus. For all other sections, treat the full existing content as the prior session(s) and apply the standard merge rules below.

- **Two labels present (`[Session A]` and `[Session B]`)**: label the new draft entry `[Session C]` and append it as its own paragraph in Recent Focus. For all other sections, treat the full existing content as the prior session(s) and apply the standard merge rules below.

- **Single unlabeled Recent Focus** (standard case - first merge): label the existing entry `[Session A]` and the new draft entry `[Session B]`, each on its own paragraph.

**Merge rules (existing file = prior session(s), new draft = newest session):**

- **Header line** (`*Written by /ds-wrap...`): replace with a new line using today's date and the note "(merged context)". Keep the `*Project:` line from the new draft.
- **Recent Focus**: apply the labeling logic above.
- **Current Task / Next Steps**: combine all items from both. Remove exact duplicate lines. Keep all non-duplicate items.
- **Key File Paths**: union both lists. Remove exact duplicate lines.
- **Watch Out For**: union both lists. Remove exact duplicate lines. If one had "None" and the other has real entries, use only the real entries.
- **Tools Used**: combine both comma-separated lists, split by comma, trim whitespace, deduplicate, re-join as a single comma-separated list.

Write the merged result to disk. Result: "Merged context written to [path] (combined sessions)."
