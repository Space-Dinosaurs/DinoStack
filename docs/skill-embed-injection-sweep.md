# Skill-embed injection sweep runbook

## Why this exists (DS-45)

`scripts/check-skill-embed-budget.sh`'s `CEILING` constant (139,160 B) was
written up as "a safety boundary" anchored to a single empirically-confirmed
verbatim-injection point (127,107 B). Tracing both figures found that
`CEILING` is actually `1.1x` an unrelated 2026-08-07 build-size snapshot
(126,509 B), not `1.1x` the injection-confirmed figure, and the
injection-confirmed figure's own provenance (which build, which session,
which harness version) was never recorded. See `scripts/check-skill-embed-budget.sh`'s `CEILING`
comment for the full correction.

The only prior injection observation on record (DS-146: 130,015 B, canaries
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
  `.claude/skills/dinostack/SKILL.md`; `--out` is refused outright if it
  resolves to that path.
- `scripts/skill-embed-sweep-harness.sh install` is the only subcommand that
  touches the real file, and only when explicitly invoked. It always writes a
  timestamped backup first, verifies that backup byte-identical via `cmp`
  before proceeding, and prints the exact restore command.
- `scripts/skill-embed-sweep-harness.sh restore` copies a backup back over the
  real file and verifies the result is byte-identical to the backup via
  `cmp` - not by re-running the build and trusting it.

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
  truncation; all three together make a coincidental false "looks complete"
  read implausible.

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

Then independently confirm the working tree is clean against the last
committed/tracked build:

```
bash scripts/build-all.sh
git status --short -- .claude/skills/dinostack/SKILL.md
```

A clean `git status --short` on that path is the independent, non-"trust the
rebuild" confirmation that the restore succeeded - `restore` itself already
verifies byte-identity against the backup via `cmp`, so this step is a
second, differently-sourced check (against the git-tracked build), not a
repeat of the same one.

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
