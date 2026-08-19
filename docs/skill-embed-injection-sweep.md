# Skill-embed injection sweep runbook

## Why this exists (DS-45)

`scripts/check-skill-embed-budget.sh`'s `CEILING` constant (139,160 B) was
written up as "a safety boundary" anchored to a single empirically-confirmed
verbatim-injection point (127,107 B). Tracing both figures found that
`CEILING`'s arithmetic is actually `1.1x` a 2026-08-07 build-size snapshot
(126,509 B) - a figure the same commit's own rationale placed alongside the
injection-confirmed figure, but which the arithmetic never derives from -
not `1.1x` the injection-confirmed figure itself. See
`scripts/check-skill-embed-budget.sh`'s `CEILING` comment for the full
correction and for what the 127,107 B figure's own provenance is and is
not traceable through.

A prior injection observation on record (DS-146: 130,015 B, canaries
present at head and tail, no truncation, no performance warning) was never
written down as a repeatable procedure - nobody could reproduce it without
reconstructing it from prose. This runbook, plus
`scripts/skill-embed-sweep-harness.sh` and
`scripts/lib/skill_embed_sweep.py`, close that gap.

**This runbook does not itself resolve the CEILING provenance gap.** Running
the sweep and deciding whether to raise `CEILING` from the result is a
separate, explicit follow-up - do not treat completing this runbook once as
license to bump `CEILING`.

## What the harness does and does not do

- `scripts/skill-embed-sweep-harness.sh candidate` builds a byte-exact
  candidate `SKILL.md` at a chosen target size by padding the currently-built,
  real `SKILL.md` with inert, obviously-synthetic marker lines - never real
  methodology prose. It **never** writes to the real, tracked
  `.claude/skills/dinostack/SKILL.md` of this checkout, or of any other
  checkout on the machine; `--out` is refused outright if it resolves to the
  same on-disk file (case-insensitive-filesystem, symlink, and hardlink
  aware) or matches the `.claude/skills/dinostack/SKILL.md` artifact shape
  under a different checkout.
- `scripts/skill-embed-sweep-harness.sh install`, only when explicitly
  invoked, refuses to run if the real file it is about to back up already
  carries a DS-45 sweep
  canary (a previously-installed padded build, not a trustworthy backup
  source); otherwise it always writes a timestamped backup first, verifies
  that backup byte-identical via `cmp` before proceeding, and prints the
  exact restore command.
- `scripts/skill-embed-sweep-harness.sh restore` refuses to run if the
  `--backup` it is about to restore FROM already carries a DS-45 sweep
  canary (the backup itself was padded, not genuine) - checked before the
  real file is touched at all, so a bad backup is refused harmlessly
  rather than overwriting the real file first (DS-45 round-3 Major 1).
  Otherwise it copies the backup over the real file and verifies the
  result is byte-identical to the backup via `cmp` - not by re-running
  the build and trusting it.

## Canary scheme (what a reader looks for)

Every candidate carries three detectable markers:

- **Head canary**: `<!-- DS-45-SWEEP-HEAD sweep_id=<id> target_bytes=<n> -->`,
  inserted as the first line immediately after the YAML frontmatter's closing
  `---` (not at byte 0, since the real file's frontmatter must stay parseable
  as valid skill metadata).
- **Numbered pad-line run**: `<!-- DS-45-SWEEP-PAD sweep_id=<id> seq=NNNNNN -->`
  lines, sequentially numbered from `000001` to a declared total. A gap in the
  sequence, or a malformed last line, means the run was cut short.
- **Tail canary**: a block ending in the literal line
  `DS-45-SWEEP-END-OF-FILE -->`, which also declares the total pad-line count
  and a sha256 of the pad-line block. This is what tells a reader "this is
  genuinely the end of the file" rather than "this is where truncation
  happened to stop and it looked clean" - a truncation before the true end
  either cuts a pad line mid-line (visibly malformed), stops the numbered run
  short of its declared count, or drops the `DS-45-SWEEP-END-OF-FILE` marker
  and its hash entirely. Any one of the three is sufficient evidence of
  truncation of the pad block/tail region; all three together make a
  coincidental false "looks complete" read of that region implausible.
  **This scheme proves the padding and tail survived intact - it does not
  independently verify that the base methodology content earlier in the
  file (before the head canary) is complete or unmodified.** A mid-file
  elision that drops some base content while leaving the head canary, the
  full numbered pad run, and the tail block all intact would pass all
  three checks above undetected. If verifying base-content completeness
  matters for a given sweep, cross-check it separately (e.g. `git diff`
  the base content against the last committed build) - this canary scheme
  was not built to cover that class of truncation.

To verify a candidate's tail canary from inside a session:

1. Confirm the file's (or the injected context's) last non-blank line is
   exactly `DS-45-SWEEP-END-OF-FILE -->`.
2. Count the `DS-45-SWEEP-PAD` lines actually visible and compare to the
   `declared_total_pad_lines` value in the tail block.
3. If filesystem access is available (`Read`/`Bash` in the same session),
   independently recompute the sha256 of the pad-line block and compare to
   `pad_block_sha256`.

## Procedure

### Step 1 - build a candidate (agent-executable, no fresh session needed)

```
bash .claude/build.sh   # ensure the real SKILL.md reflects current content/
bash scripts/skill-embed-sweep-harness.sh candidate \
  --target-bytes 150000 \
  --out /tmp/ds45-candidate-150000.md
```

Repeat with different `--target-bytes` values for a sweep across several size
points (e.g. 140000, 145000, 150000, 160000). This step, and choosing the
size points, can be done by an agent in the current session - no fresh
session is required to build candidates.

**Repeating the full Steps 1-4 loop across multiple size points:** run Step 4
(restore) to completion before starting Step 2 (install) for the next size
point. `install` refuses outright if the real file it is about to back up
already carries a DS-45 sweep canary (it would be a previously-installed
padded build, not the genuine one) - so installing a second candidate
without restoring the first in between is a hard stop, not a silent
backup-of-padding (DS-45 round-2 Major 2).

### Step 2 - install a candidate for a live test (human-authorized, agent-executable)

```
bash scripts/skill-embed-sweep-harness.sh install \
  --candidate /tmp/ds45-candidate-150000.md
```

Note the printed backup path and restore command. This step mutates the real,
tracked `SKILL.md` on disk (though it is git-tracked, so the working tree
will show a diff) - do not run this on a machine where the real file's
current state matters until you have the restore command in hand.

### Step 3 - start a fresh session and invoke the skill (human-only, cannot be automated)

This is the step no agent working inside the current session can do for
itself: the whole point is to observe what a **new** session's context
actually contains after it invokes `/dinostack`, which requires starting a
new session from outside the one running the sweep.

1. Start a brand-new Claude Code session in this repo.
2. Invoke the `/dinostack` skill (or trigger it naturally).
3. In that fresh session, check for the head canary near the top of the
   injected content, and apply the three-point tail-canary check above.
4. Record: did the full tail canary (all three checks) appear intact? Was
   there any visible truncation, warning, or performance degradation?

### Step 4 - restore the real file (agent-executable)

```
bash scripts/skill-embed-sweep-harness.sh restore \
  --backup <path printed by install in Step 2>
```

`restore` itself already refuses, before touching the real file, if the
`--backup` it was given carries a DS-45 sweep canary (which would mean the
backup itself was padded, not genuine - DS-45 round-2 Major 2, DS-45
round-3 Major 1), and otherwise verifies the restored file byte-identical
against the backup via `cmp`.

For a second, differently-sourced confirmation, check the restored file
against git's already-committed copy **before** running anything that
regenerates it:

```
git status --short -- .claude/skills/dinostack/SKILL.md
```

Run this in this order, not after `bash scripts/build-all.sh`. `build-all.sh`
regenerates `SKILL.md` from `content/` regardless of whether `restore`
succeeded, so a `git status --short` taken *after* a rebuild is clean whether
or not restore actually worked and proves nothing (DS-45 round-2 Major 1 -
this step previously suggested running the rebuild first, which made the
confirmation vacuous). A clean status taken directly on the restored file, as
above, means it is already byte-identical to the last committed build; there
is no need to also run `build-all.sh` for this confirmation.

### Step 5 - record the result

Do not draw a truncation-boundary conclusion from a single data point (see
DS-45's non-goal note above). Record each size point's outcome (installed
size, tail-canary-intact yes/no, any harness warning observed) so a later
pass can look for a pattern across the swept points before touching
`CEILING`.

## Repeatability

Every step above is scripted and reusable except Step 3, which structurally
requires a human to start a fresh session (an agent working inside the
session performing the sweep cannot observe what a *different*, *new*
session's context contains). Re-running this runbook at a later date, or
after `content/` grows, requires no new tooling - just new `--target-bytes`
values and a fresh Step 3 per value.
