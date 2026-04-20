# cleanup-worktrees component eval

Measures whether `content/commands/cleanup-worktrees.md` makes the right
keep/remove decisions across a seeded git worktree topology, including
clean isolation worktrees, dirty ones, feature worktrees with merged or
open PRs, the `gh` CLI being missing, and unknown-branch shapes.

## What this measures

- **Removal correctness:** did the command remove the worktrees it should
  have (clean isolation worktrees, feature worktrees whose PR is MERGED)?
- **Preservation correctness:** did the command leave alone the
  worktrees it should have left (dirty ones, feature worktrees with
  OPEN PRs, unknown-shape branches)?
- **Branch hygiene:** were the corresponding local branches deleted when
  the worktree was removed, and preserved when the worktree was?
- **Report fidelity:** does the final report mention the right
  substrings (e.g. "manual review", "gh not available") and avoid
  forbidden ones (e.g. claiming a preserved worktree was removed)?
- **Safety invariant:** the main worktree (repo root) MUST NEVER be
  removed. A violation hard-floors the score to 0.0 regardless of the
  rest.
- **Stray avoidance:** worktrees remaining at the end that were neither
  expected-preserved nor the main worktree count as strays (soft-capped
  at 3).

## What this does NOT measure

- **Live `gh` API calls.** `gh pr list` is proxied through a per-fixture
  stub placed on `$HOME/bin`. The stub returns deterministic JSON for
  the branches the fixture declares. Maintainer edits to `gh` flag
  handling or output parsing are only tested against the stub's
  contract, not the real GitHub API surface.
- **The `.git` directory layout of a production repo.** Each fixture
  seeds a minimal local-only git repo via `seed.sh`. There is no remote
  beyond what `seed.sh` configures, and `git fetch origin` in Step 1 is
  expected to fail silently (the command tolerates this by design).
- **Concurrency.** Worktree state is seeded synchronously; the command
  runs serially. A maintainer edit that introduces a race is out of
  scope.

## Invocation caveat (proxy disclosure)

The eval inlines the verbatim body of
`content/commands/cleanup-worktrees.md` into the `-p` prompt, the same
proxy pattern used by the init-project and wrap evals. Slash-command
dispatch is not reachable under a redirected `$HOME`. We measure the
COMMAND BODY as executed by a top-level Claude session with
Read/Grep/Glob/Task/Write/Edit/Bash and `--permission-mode acceptEdits`.

## Seed hook

A `seed.sh` at each fixture root is executed by the runner after the
Tier 2 worktree is materialized, with cwd=worktree and HOME pointed at
the fake home. The script's job is to turn the copied-in `repo/`
subtree into an actual git repo and realize the target worktree
topology using `git worktree add` commands. It also writes the
`gh`-stub to `$HOME/bin/gh` when the fixture needs one.

The scorer reads `.git` via `git -C <worktree_root> worktree list` and
`git -C <worktree_root> branch` on the SAME worktree the command ran
in. `worktree_root` is stashed on the run record by the runner before
the Tier 2 isolator cleans up.

## Isolation

Tier 2: worktree tmpdir seeded from `fixture/repo/`, plus a separate
fake `$HOME` tmpdir. The invoker prepends `$HOME/bin` to `PATH` when a
fake home is in use so the `gh` stub shadows any real `gh` on the
developer's machine.

## OVERFITTING-RULE pointer

See `evals/OVERFITTING-RULE.md`. Common temptations on this component:

- Adding a synonym map so "skip" / "skipping" / "left alone" all match a
  single substring check. Don't - enforce vocabulary in the prompt's
  Required outputs block.
- Editing the command body to remove the "needs manual review" phrase
  because one fixture's report did not include it. Don't - if the
  phrase genuinely does not belong, the command-doc change should
  survive the fixture being deleted.
