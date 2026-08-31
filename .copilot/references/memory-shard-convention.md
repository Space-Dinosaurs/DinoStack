# Memory shard convention

```
Purpose: Defines the git-tracked shard directory a project's root MEMORY.md
         is compiled FROM, and the frontmatter every shard file carries.
         See "Status" below for what exists today (DS-221 Unit 1).
Public API: Directory `.agentic/memory-shards/` (git-tracked, one fact
            per file, plus one structural artifact - see "Preamble
            artifact" below); filename shape `<YYYY-MM-DD>-<slug>.md`
            (date is for human scanning only - it carries NO ordering
            semantics, see "Filename" below); frontmatter shape `name`
            / `description` / `metadata.type` / `sequence` /
            `supersedes` / `superseded_by` (all defined below).
Upstream deps: none - this is a standalone convention doc, generic to
               any project. It names no project-specific ticket prefix,
               path, or workspace.
Downstream consumers: `bin/ds-memory-shard` (DS-221 Unit 1, SHIPPED),
                       which reads `_preamble.md` plus every fact shard
                       under `.agentic/memory-shards/`, sorts by
                       `sequence`, and compiles a project's root
                       `MEMORY.md` from them (see "Compiled output
                       shape" below for exactly what it emits around the
                       shard bodies); a later unit's `/ds-wrap` Part E
                       writer wiring (NOT YET WIRED - Unit 1 ships the
                       compiler only, gated inert by the
                       `memory_shard_mode` toggle, default `false`),
                       which will write one new shard file per captured
                       fact instead of inlining prose into `MEMORY.md`;
                       and any future pruning change, which edits or
                       deletes individual shard files and re-runs
                       `regenerate --allow-removal` rather than touching
                       the compiled `MEMORY.md` directly.
Failure modes: `regenerate` REFUSES and writes nothing whenever
               compiling the current shard set would drop any entry
               present in `MEMORY.md` - see "Regenerate's entry-loss
               and reordering guards" below; `--allow-removal`
               overrides this for a deliberate prune. A shard filed
               without a `metadata.type` or a `sequence` is rejected
               loudly by the compiler, naming the offending file.
```

## Status (DS-221 Unit 1 - compiler shipped, writers NOT wired)

`bin/ds-memory-shard` (backed by `hooks/lib/memory-shard.js`) exists and can
`split` an existing `MEMORY.md` into `.agentic/memory-shards/` (a git-tracked
`_preamble.md` plus one shard file per entry) and `regenerate` recompiles
`MEMORY.md` from them byte-for-byte. **Nothing calls this yet.** `/ds-wrap`
Part E, wrap-ticket, and `/ds-memory-update` do not write shards on new-fact
capture - that wiring is a later unit's scope. The `memory_shard_mode`
project-config toggle ships `false` and is read by nothing; every existing
project behaves exactly as it did before this convention existed.

**Interim rule, stated plainly because it is easy to get backwards: keep
appending new facts DIRECTLY to `MEMORY.md` by hand, exactly as every session
has always done - this remains explicitly safe.** Nothing writes a shard for
a hand-appended entry yet, and `regenerate` is built to make that safe rather
than merely hope for it: because it REFUSES to write `MEMORY.md` whenever the
current file contains an entry line the shard set does not (see "Regenerate's
entry-loss and reordering guards" below), a hand-appended entry cannot be
silently dropped by a later `regenerate` run - the command will name it and
refuse instead. The correct response when that refusal fires is
`split --force` (to capture the hand-appended entry into a fresh shard set),
then `regenerate` again.

Shard-first authoring becomes the rule only once a later unit wires writer
support - not before. Until then, the Filename/Frontmatter sections below
describe the convention the compiler already consumes; ordinary session
capture should keep targeting `MEMORY.md` directly.

## Directory

`.agentic/memory-shards/` - **git-tracked**, unlike its sibling
`.agentic/memory/` (a different, gitignored, machine-local Claude Code
auto-memory directory this convention does not touch, rename, or supersede).
`.agentic/` is gitignored wholesale by the project-scaffolding umbrella
(`.agentic/*`) with explicit `!` carve-outs for the handful of paths a
project tracks; `.agentic/memory-shards/` is one of those carve-outs as of
scaffolding version 8 (see `content/project-scaffolding.yml`, and the
Verification section below).

These facts are not throwaway session output - they are the same class of
durable, cross-session knowledge `MEMORY.md` has always held. Git-tracking
the shard directory is what makes pruning, correction, and supersession
reviewable as an ordinary small PR - a one-shard PR is exactly the size that
kind of review is designed to make trivial to reason about.

## Filename

```
<YYYY-MM-DD>-<slug>.md
```

- `<YYYY-MM-DD>` is a date extracted from the entry's own first line for
  human-scanning convenience only (falls back to `0000-00-00` when the
  entry's opening line does not carry a recognizable date - the convention
  is deliberately format-agnostic across projects, since not every project's
  `MEMORY.md` entries open with a bold date the way some do).
- `<slug>` is a short kebab-case identifier for the fact, unique enough
  within that date to avoid a filename collision (e.g.
  `2026-08-29-ds-221-memory-shard-convention.md`).
- Two shards captured the same day on unrelated topics get two files with
  the same date prefix and different slugs - this is expected, not a
  collision.

**The date prefix carries no ordering semantics - do not sort shards by
filename.** A real-world corpus of this shape is not guaranteed to be
strictly date-ordered: corrections are sometimes filed immediately adjacent
to the entry they correct rather than at their own date's position, and
other stretches of a long-lived file can legitimately run in a different
order for reasons no single mechanism explains. A compiler that reproduced
order by sorting on the filename's date segment would silently reorder
history and break byte-identity against the pre-split file - which is the
one property this convention's split/regenerate round trip is required to
prove, and which is why sorting on date is rejected regardless of why any
individual entry sits where it does.

**The actual sort key is an explicit `sequence` integer in each shard's
frontmatter** (see Frontmatter below), assigned at split time from each
entry's existing position in `MEMORY.md`. Sorting on `sequence` is
deterministic, independent of filesystem enumeration order, and reproduces
the exact order the file had at split time. The date prefix exists purely so
a human scanning the directory listing can find roughly-when a shard was
captured; it is not consulted by the compiler's sort.

**`sequence` values are GAP-SPACED, not consecutive: `sequence = ordinal *
1000`** (shard 1 gets `1000`, shard 2 gets `2000`, ...). This is deliberate,
and it is what makes filing a correction beside the entry it corrects
achievable without renumbering the corpus: inserting a new entry between two
originally-adjacent shards means picking any unused integer strictly between
their two `sequence` values (999 are available between any originally-
adjacent pair) - assign it in the new shard's frontmatter and nothing else
changes. Only if a local gap is fully exhausted (many insertions clustered in
the same spot) does anything need renumbering, and only the entries in that
local neighborhood, never the whole corpus. The compiler accepts any integer,
so this never needs a non-integer scheme.

**Filenames carry NO positional information - the slug segment is derived
from CONTENT, not from the entry's ordinal or `sequence`.** It is
`<first-ticket-reference-in-the-entry, or "session">-<8-hex-char SHA-256 of
the entry body>`, where "ticket reference" is a generic `PREFIX-123` shaped
pattern (never a hardcoded project-specific ticket prefix, per the
universality constraint this convention is bound by). This is deliberate:
coupling a filename to position would mean every insertion or renumbering
renames files, which defeats the whole point of gap-spacing. **The ticket
segment is a scanning aid only, not an attribution claim** - an entry that
merely mentions a ticket in passing (without being filed under it) still gets
that segment in its filename. Treat the frontmatter/body as the source of
truth for what an entry is actually about; the filename is not evidence of
it.

## Preamble artifact

The preamble (everything in `MEMORY.md` before the first `- `-prefixed
line - see "Compiled output shape" below) is captured as its own shard file,
`_preamble.md`, under `.agentic/memory-shards/` - a reserved filename,
written by `split`, carrying no frontmatter (it is a structural artifact, not
a fact). `regenerate` reads it directly and emits it verbatim as the
compiled file's opening. **This is how `MEMORY.md`'s own header text becomes
editable without touching the compiler at all**: edit `_preamble.md`, then
run `regenerate --allow-removal`. **Plain `regenerate` (no flag) REFUSES
here** - a header edit removes the old header's lines from the compiled
output, which is exactly what the entry-loss guard below exists to catch, so
it is not the wrong command, it is the command running without the
confirmation a removal needs. **And `split --force` is NOT the remedy
either, even though it is the refusal's usual suggestion for other cases
(see below)**: run before `regenerate`, `split --force` re-derives
`_preamble.md` from the CURRENT `MEMORY.md`, which still has the OLD header
at that point - it silently reverts the edit rather than committing it.

## Regenerate's entry-loss and reordering guards

`regenerate` refuses to write `MEMORY.md` - and writes NOTHING - whenever
compiling the current shard set would drop ANY LINE present in the current
`MEMORY.md`: preamble text, the `# Memory` heading, an entry's first line, a
continuation line, a blank separator - every physical line, not merely
`- `-prefixed entry lines. This is a CONTENT check (every current line must
survive into the compiled output, by multiset count), not a count check -
swapping one line's content for another while holding the count constant
still triggers the refusal, and a substring-containment check would silently
treat reordered or partial content as present, which this also does not. On
refusal, the command names how many lines would be lost and previews them,
then exits nonzero without touching `MEMORY.md`.

The common trigger is exactly the case this doc's Status section describes
as safe: a hand-appended `MEMORY.md` entry that has not yet been captured
into a shard. The refusal's own message says what to do - re-run
`split --force` to pick it up, then `regenerate` again (no `--allow-removal`
needed for that path: nothing is lost, only added).

**`regenerate` separately refuses (also without `--allow-removal`) when zero
lines are lost but the compiled output would REORDER lines relative to the
current `MEMORY.md`.** Entry order is load-bearing in this file, so this
catches a hand-edited shard `sequence` that moves an entry PAST a
neighbor - as opposed to a legitimate insertion, which fills an unused gap
BETWEEN two neighbors and does not reorder anything that was already there,
in ANY position. If `MEMORY.md`'s current order is correct and the shard
edit is the mistake, `split --force` re-derives the shard set from
`MEMORY.md`'s own order and fixes it; if the new order is genuinely
intended, `--allow-removal` accepts it (the flag name covers both content
removal and reordering - it is the general "yes, I mean this deliberately"
override for either guard).

**`--allow-removal` overrides both guards** for a deliberate prune or an
intentional reorder: delete or edit the shard(s) involved, then run
`regenerate --allow-removal` to recompile without the refusal.

`split` has its own, separate refusal on the OTHER side of this transaction:
when reconciling `shardDir` against `MEMORY.md` would delete more than a
small threshold (3) of orphaned shard files (a hand-edited entry's stale
prior shard, multiplied across enough edits at once), `split --force` alone
refuses too, and needs `--force --allow-removal` together to proceed -
always printing every orphan's filename first, whether the threshold gate
fired or not. Ordinary single-entry reconciliation stays fully automatic
under plain `--force`; this exists because `split --force` is the very
remedy the refusals above point at, so it must not itself be an unguarded
bulk delete.

## Frontmatter

Every shard file opens with YAML frontmatter:

```yaml
---
name: <slug>                     # matches the filename's <slug> segment
description: >-
  <one-line summary of the fact, suitable for a retrieval index; this is
  NOT the fact itself - the fact is the markdown body below the
  frontmatter>
metadata:
  type: project | feedback | reference | user
sequence: <integer>              # the compiled-file sort key - see
                                  # "Filename" above. Assigned once, at
                                  # split time, from the entry's existing
                                  # position in MEMORY.md; never derived
                                  # from the filename date.
supersedes: []                   # list of shard filenames this entry
                                  # replaces, if any (usually empty)
superseded_by: null              # filename of the shard that replaces
                                  # this one, or null while still current
---
```

Field notes:

- **`metadata.type` is a short, fixed enum** - `project`, `feedback`,
  `reference`, `user`. Extend it only if a captured fact genuinely does not
  fit any of the four; keep it a short enum, never free text. **The
  compiler's one-time split does NOT perform per-entry semantic
  classification: every shard it produces carries a uniform `type: project`,
  the mechanical default consistent with a "mechanical, no semantic
  judgment" split** - it is not currently a meaningful filtering signal, even
  though many entries plainly read as `feedback`- or `reference`-class. A
  future classification pass may refine individual shards' `metadata.type`;
  do not read the uniform value as evidence anyone looked.
- `sequence` is a plain integer, unique across all shards, assigned at split
  time from each entry's existing position in `MEMORY.md` (lower `sequence`
  = earlier in the compiled file). The ordinary case - a new fact authored
  after the split - takes the next unused integer (append to the end).
  Inserting a new shard so it reads as sitting beside an existing older
  entry (mirroring how a correction is often filed) uses `fillSequenceRun`'s
  gap-spacing arithmetic (see `hooks/lib/memory-shard.js`); this doc fixes
  the meaning of the field (a total order over shards), the library owns the
  exact insertion arithmetic.
- `supersedes: []` names zero or more prior shard **filenames** (not slugs
  alone, since two shards can share a slug on different dates) that this
  entry replaces in whole or in part. Most shards supersede nothing.
- `superseded_by: null` is the reverse edge, set on the OLD shard once a
  newer one supersedes it - written by whichever change adds the superseding
  shard, mirroring the discipline a well-kept `MEMORY.md`'s prose annotations
  already follow (never silently delete a superseded fact; mark it and keep
  it, unless it is later proven to add nothing beyond the correction
  itself).
- The markdown body below the frontmatter is the fact itself, in whatever
  register the project's existing `MEMORY.md` bullets use - this convention
  does not ask for a rewrite of tone or content, only for the fact to live in
  its own file.

## Compiled output shape

Every entry in `MEMORY.md` is expected to be one unbroken run of physical
lines starting `- ` (a markdown bullet) at the top level - the compiler
locates entry boundaries by finding lines that start with `- ` at column 0.
What is NOT a fixed, countable property of the file: how much whitespace
sits between entries, or how many lines the preamble occupies. Both can vary
across a file's history, so this section specifies WHAT THE SPLITTER
CAPTURES rather than stating either number as a constant - a stated count
here would go stale the moment either shape changes:

- **Preamble.** Everything in `MEMORY.md` before the first entry boundary
  (the first line starting `- `) is the preamble - captured verbatim by the
  splitter at split time and stored as its own shard artifact,
  `_preamble.md` (see "Preamble artifact" above), not as a count of any kind
  stated in this document.
- **Shard body.** Each shard's stored body is the entry's own line starting
  `- `, PLUS any blank line(s) or continuation line(s) that immediately
  follow it in `MEMORY.md` up to (but not including) the next entry's `- `
  line or end of file - captured verbatim, whether that is zero blank lines
  or several. This is what lets a straight concatenation reproduce
  `MEMORY.md`'s actual inter-entry spacing without the compiler, or this
  document, needing to know how much of it exists anywhere: each shard
  already carries its own trailing whitespace as part of its captured
  content.
- **Compile.** The compiled file is the preamble followed by every shard's
  body concatenated in `sequence` order, with NO separator inserted between
  them by the compiler itself - separation, where it exists, is already
  inside the preceding shard's captured body.
- **Byte-identity against the pre-split file is what proves this captured
  everything correctly - not a stated line count or blank-line count.** If
  the compiled output and the pre-split file ever diverge, the splitter
  under-captured something at a boundary; the fix belongs in the splitter's
  boundary logic, never in a number restated here.

## Universality

This convention names no project-specific identity, workspace, tracker, or
path. The slug's ticket-reference segment matches a generic `PREFIX-123`
pattern rather than a hardcoded prefix; the CLI's `--dir` flag resolves
`.agentic/memory-shards/` and `MEMORY.md` relative to whatever project
directory is passed, defaulting to the invoking process's own working
directory. A teammate with different credentials, a different tracker, or a
different harness gets identical behavior.

## Verification

**Use the PLAIN (non-verbose) form as the pass/fail signal:**

```
git check-ignore -q .agentic/memory-shards/2026-01-01-example.md
```

Exit code **1** (no output) means the path is NOT ignored - correct, once
the project-scaffolding carve-out for this directory is in place (see
`content/project-scaffolding.yml` scaffolding version 8). Exit code **0**
(path printed) means it IS ignored - the carve-out is missing or broken.

**The bare directory negation is what actually does the work here.**
Measured directly on git 2.55.0 against this manifest's `.agentic/*`
umbrella (a one-level glob - not the bare/recursive `.agentic/` form that
cannot be pierced by any negation at all): `!.agentic/memory-shards/` alone
is SUFFICIENT to un-ignore every path nested under it, including files
several directories deep. The sibling `!.agentic/memory-shards/**` negation
is REDUNDANT in the bare form's presence, and on its OWN (without the bare
form) is actually INSUFFICIENT - it never un-ignores the directory entry
`.agentic/*` itself matches, so nothing under it is reached. Both lines
ship anyway, matching the existing `!.agentic/session-log/**` precedent
(the identical measured redundancy already documented for that carve-out) -
a deliberate defense-in-depth choice, not a correctness requirement. Do not
restate the older "both lines are required" framing this section used to
carry; it was not supported by measurement.

**Do not use `git check-ignore -v`'s exit code as the criterion - it does not
discriminate.** `-v`'s exit code reports "some pattern matched", including a
NEGATION pattern, not "the path is ignored". `-v` remains useful as a
**diagnostic** once the plain form has told you pass/fail: it prints WHICH
`.gitignore` line and file:line matched, which is the fast way to find a
broken carve-out. But treat its own exit code as informational only, never
as the check.

Confirming the carve-out works is what makes a shard written here visible to
`git status`/`git add` in every worktree, not silently dropped the way a
file landing in a gitignored path can be otherwise.
