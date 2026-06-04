# update-agentic-engineering eval

Tier 2 command-mode eval for `/update-agentic-engineering`.

## What this measures

End-to-end decision + edit + build + commit + push behavior of the
command against a seeded miniature agentic-engineering checkout. Five
fixtures span the Step 0 decision matrix:

- uae-001 clean / local == origin / rules edit -> happy_push (no build).
- uae-002 clean / local == origin / commands edit -> happy_push + build.
- uae-003 origin-ahead / clean -> ff_pull, then edit + push.
- uae-004 both-ahead divergent -> stop_divergent (no edit/commit/push).
- uae-005 dirty tree with WIP on the edit target -> stop_dirty (no
  auto-stash).

Scoring axes (sum 1.0): w_decision (0.25), w_edit (0.20), w_build
(0.10), w_commit (0.20), w_push (0.15), w_forbidden (0.10). Edit,
build, commit, and push are vacuous on STOP decisions so a correct
STOP still scores well.

## Proxy caveats

- **Fake origin.** The runner does not touch Space-Dinosaurs. The prompt-layer
  setup hook (`evals.runner.prompt`) initializes the seeded repo as a
  local git repo and creates a sibling bare repo as `origin`. All
  `git fetch/pull/push` traffic stays on the local filesystem inside
  the isolated worktree tmpdir. Push behaviour observed here reflects
  command logic, not network realities; real-world rejection races,
  auth failures, and SSH host-key issues are not exercised.
- **Step 2 user approval auto-granted.** Production `/update-agentic-
  engineering` waits for explicit human approval after presenting the
  diff. The prompt's non-interactivity directive tells the run to
  treat Step 2 approval as auto-granted for the eval run only. The
  human-gate mechanism itself is therefore not measured.
- **Permission-blocked path not tested.** The command's "if a spawned
  Worker returned BLOCKED citing Edit permission denial, the main
  session may apply the edit directly" carve-out is not exercised by
  any current fixture. No fixture simulates the
  permission-denial-from-Claude-Code path.
- **Build cmd is minimal.** The seeded `.claude/build.sh` in each
  fixture's repo is a one-liner that copies
  `content/commands/*.md` -> `.claude/commands/`. The real build
  prepends a prerequisite blockquote; the minimal script exists so the
  scorer's w_build axis can verify the command ran the build and the
  artifact was regenerated. Maintainer edits to the real build.sh are
  not reflected here.
- **STOP axes are vacuous.** w_edit, w_build, w_commit, and w_push
  score 1.0 on STOP decisions. A command that emits `DECISION:
  stop_divergent` but also (wrongly) commits will be caught by the
  commit axis's non-vacuous STOP check (head advance > 0 flips commit
  credit to 0.0).
- **Forbidden-action axis is regex-on-transcript.** Only tokens that
  appear in the run's `final_text` or stderr are detected. A command
  that executes `git reset --hard` via a nested Bash call that does
  not echo it verbatim into the transcript will evade this axis. The
  commit-axis head-advance check is the safety net.

## Decision vocabulary

The prompt tells the run to emit exactly one of:

- `proceed`
- `ff_pull`
- `stop_divergent`
- `stop_dirty`
- `happy_push`

as a line of the form `DECISION: <class>` near the end of its output.
The scorer exact-matches this against each fixture's
`expected_decision`.

## Fixtures

| id | pre-state | decision | edit | build? | HEAD advance | origin updated? |
|---|---|---|---|---|---|---|
| uae-001 | clean, local==origin | happy_push | content/rules | no | 1 | yes |
| uae-002 | clean, local==origin | happy_push | content/commands | yes | 1 | yes |
| uae-003 | origin-ahead 3 | ff_pull | content/rules | no | 4 | yes |
| uae-004 | both-ahead | stop_divergent | (none) | no | 0 | no |
| uae-005 | dirty WIP | stop_dirty | (none) | no | 0 | no |

## Not measured

- SSH/HTTPS remote handling
- Multi-remote disambiguation
- Pre-commit-hook failure paths
- Race recovery on push-rejected (`git pull --rebase` retry path)
- Real `.claude/build.sh` semantics (prerequisite-blockquote prepend)
- Symlink-consistency between `content/` and
  `.claude/skills/agentic-engineering/` (tested via direct edit to
  `content/` only).
