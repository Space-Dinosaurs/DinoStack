# init-project component eval

Measures whether `content/commands/init-project.md` produces the right
scaffolding when run against a seeded project.

## What this measures

- Does the command produce every file it must (AGENTS.md, CLAUDE.md,
  `.claude/settings*.json`, `.claude/findings.md`, `.agentic/preferences.json`,
  `docs/*/.gitkeep`, `.gitignore`)?
- Does it correctly emit conditional files keyed on detected signals
  (`.claude/qa.md` for web UI, `.claude/deploy.md` for release,
  `.claude/tracking.md` for tracker)?
- Does it NOT emit files whose signals are absent?
- Does AGENTS.md carry the required sections and stay under the line budget
  (45)?
- Does `.gitignore` contain the mandatory entries
  (`.claude/settings.local.json`, `.agentic/`)?

## What this does NOT measure

- Interactive quality. The runner injects a non-interactivity directive so
  every prompt in the command body (tracker selection, Linear migration,
  "Proceed?" confirmations) is auto-answered with the discovered defaults.
  Real-user interaction quality is out of scope.
- Prose quality inside AGENTS.md. The scorer checks structural presence of
  required section headings and a line budget; it does not judge whether
  the description, Decisions, or Conventions prose is good.
- Per-track AGENTS.md. Fixtures are single-track.
- Linear / Jira API connectivity. Tracker setup runs are short-circuited by
  the non-interactivity directive; only the scaffolded file's presence is
  checked.

## Invocation caveat (proxy disclosure)

The eval inlines the verbatim body of `content/commands/init-project.md`
into the `-p` prompt. This is **not** a real `/init-project` slash-command
dispatch: under a redirected `$HOME`, the command is not discoverable
because the skill / command install path is absent. Characterization
confirmed `claude -p "/init-project"` returns `Unknown command:
/init-project` in this configuration.

Implication: we measure the COMMAND BODY executed by a top-level Claude
session with Read/Grep/Glob/Task/Write/Edit/Bash tools and
`--permission-mode acceptEdits`. We do not measure the slash-command
plumbing itself. This is a proxy acceptable for scoring the command's
intent + content, not for validating command installation.

## Isolation

Tier 2: worktree tmpdir seeded from `fixture/repo/`, plus a separate fake
`$HOME` tmpdir with a seeded `.claude/agentic-engineering.json` per
`fixture.inputs.home_config`. The subprocess runs with HOME pointed at
the fake dir so it never touches the developer's real `~/.claude/`.

## OVERFITTING-RULE pointer

See `evals/OVERFITTING-RULE.md`. Common temptations on this component:

- Adding a "synonym map" to the scorer so AGENTS.md written with `#
  Project` instead of `# ` still counts. Don't. Enforce vocabulary in the
  prompt's Required outputs block.
- Editing the command body to rename a file so one low-scoring fixture
  matches. Don't - if the rename is a good change, it would survive the
  fixture being deleted.

## Non-interactive mode degradation

Any /init-project path that normally prompts (Step 1 overrides, Step 2a
"Proceed?", Linear / Jira / tracker selection) is forced to
auto-discovered defaults under this eval. Any behavior that only emerges
from a user-typed correction or a non-default tracker answer is invisible
to this component. Fixtures should be designed so discovery alone
produces the target outputs.
