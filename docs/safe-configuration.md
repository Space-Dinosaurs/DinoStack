# Safe configuration

How to configure DinoStack so the agent has enough access to work while the
destructive edges are railed off. This is the operational companion to
[SAFETY.md](../SAFETY.md) (posture), [threat-model.md](threat-model.md) (what
the configuration defends against), and
[secrets-and-permissions.md](secrets-and-permissions.md) (where secrets live).
Report flaws via [SECURITY.md](../SECURITY.md).

Throughout: the configuration here is a **safety rail, not a sandbox**. It
reduces the chance and blast radius of a bad action; it does not make harm
impossible.

## Permission modes

The Claude Code installer ([`.claude/install.sh`](../.claude/install.sh)) offers
to set `defaultMode: "bypassPermissions"` in `~/.claude/settings.json` (around
line 746). In this mode agents use tools without prompting on every call -
constant prompts otherwise stall subagents. The trade is that the deny-list and
the methodology's review process become the things standing between the agent
and a destructive action, so keeping them in place matters.

If you do not enable `bypassPermissions`, Claude Code prompts per tool call and
you approve each one manually. That is the most restrictive posture and is
appropriate for untrusted or high-stakes work.

## The deny-list

This is the single canonical listing of the deny-list rules. The recommended
permission setup adds these eight patterns to `permissions.deny` in
`~/.claude/settings.json`, defined in the `recommended_deny` array in
[`.claude/install.sh`](../.claude/install.sh) (lines 736-743):

```
Bash(git push --force*)
Bash(rm -rf*)
Bash(git reset --hard*)
Bash(git clean -f*)
Bash(sudo rm*)
Bash(dd if=*)
Bash(shutdown*)
Bash(reboot*)
```

**Merge, not overwrite.** The installer merges these into any existing deny
rules rather than replacing them (`existing_deny | set(recommended_deny)` in
[`.claude/install.sh`](../.claude/install.sh) ~754 and ~782). Your own custom
deny rules are preserved; re-running the installer only adds the missing ones.

**Finite pattern rail caveat.** Each entry matches a **specific command
pattern**. The deny-list blocks the common destructive forms, not the entire
class of destructive actions. A damaging command expressed in a way the patterns
do not match - a different tool, an indirect invocation, a wrapper script - is
not blocked. Treat the deny-list as a rail against the obvious footguns, not as
a comprehensive filter. The matching layers above the deny-list (risk
classification and Skeptic review) exist precisely because the pattern list
cannot be exhaustive.

The recommended **allow-list** (the `recommended_allow` array,
[`.claude/install.sh`](../.claude/install.sh) lines 726-733) grants `Bash(*)`,
`Write`, `Edit`, and write access to `~/.claude/` directories so routine agent
work does not stall.

## Hooks

DinoStack ships hooks in [`hooks/`](../hooks/). PreToolUse and Stop hooks are
wired into `~/.claude/settings.json` by the installer; `pre-commit` is a git
hook installed separately:

- [`enforce-askuserquestion-default.py`](../hooks/enforce-askuserquestion-default.py)
  - PreToolUse; denies a co-equal multiple-choice prompt with no recommended default.
- [`enforce-orchestrator-singularity.py`](../hooks/enforce-orchestrator-singularity.py)
  - PreToolUse; denies any `Task` spawn issued from a subagent context; disable via
  `AE_SINGULARITY_GUARD_DISABLE=1`.
- [`enforce-no-abdication.py`](../hooks/enforce-no-abdication.py) - Stop hook;
  detects a permission-seeking interrogative in the final assistant message and blocks
  the stop, injecting a "proceed" directive; opt in per-project via
  `abdication_guard_enabled: true` in `.agentic/config.json`; disable via
  `AE_ABDICATION_GUARD_DISABLE=1`.
- [`pre-commit`](../hooks/pre-commit) - rebuilds adapter outputs when `content/`
  changes and stamps the docs hub date.

Two caveats that matter for safety:

- **All hooks fail open.** On a parse or logic error they exit without
  blocking, degrading to no-enforcement rather than bricking the session. They
  are also Claude Code specific; other adapters rely on the prose rules.
- **`pre-commit` is skipped inside worktrees** (it detects the worktree git dir
  and exits early) and is a build/reminder hook, not a fail-closed security
  validator. Do not rely on it to catch anything before a commit in a worktree.

## Worktree isolation

Every implementer spawn (`engineer`, `qa-engineer`, `release-orchestrator`) runs
in an isolated git worktree branched from `main`
([content/sections/11-worktree-lifecycle.md](../content/sections/11-worktree-lifecycle.md)).
This keeps the conductor's untracked scaffolding out of Worker commits and stops
parallel Workers from contaminating one shared tree. It scopes **git state**
only - it does not isolate the host filesystem or network. Leave isolation on;
it is mandatory in the methodology and there is no in-place exception.

## Risk profiles

The methodology supports three risk profiles that move the line between Low
(direct action) and Elevated (Worker plus Skeptic). Set the profile in
`~/.claude/agentic-engineering.json` or per-project via an
`agentic-engineering-profile:` marker in `AGENTS.md`
([content/sections/04-risk-classification.md](../content/sections/04-risk-classification.md)):

- **`relaxed`** - more work treated as Low; minimal Skeptic overhead. For rapid
  iteration on well-understood code you trust.
- **`default`** - single-file locally-scoped behavioral edits are Low;
  everything else Elevated.
- **`strict`** - more work treated as Elevated; broad Skeptic coverage. For when
  correctness matters more than speed.

A stricter profile means more independent review before changes are accepted. On
sensitive or shared repos, prefer `strict`.

## Risk profiles and recommended configs

| Context | defaultMode | Deny-list | Risk profile | Notes |
|---|---|---|---|---|
| **Solo / trusted repo** | `bypassPermissions` | Enabled (8 rules) | `default` or `relaxed` | Smooth agent flow; deny-list is your rail. |
| **Shared / sensitive repo** | `bypassPermissions` | Enabled (8 rules), plus your own custom deny rules | `strict` | Maximize independent Skeptic review; keep credentials least-privilege ([secrets-and-permissions.md](secrets-and-permissions.md)). |
| **CI / headless** | Per-prompt or restricted | Enabled (8 rules) | `strict` | No TTY for confirmation prompts; do not run unattended sessions with broad write access to production state. Use short-lived scoped tokens. |

These are starting points, not guarantees. Whatever the context, review
irreversible and shared-state operations before they land - see the run-safely
checklist in [SAFETY.md](../SAFETY.md).
