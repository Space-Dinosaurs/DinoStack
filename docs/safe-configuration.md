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

For a complete list of every setting and its default, see [configuration-reference.md](configuration-reference.md).

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
[`.claude/install.sh`](../.claude/install.sh)) grants `Bash(*)`, the bare
`Write` and `Edit` tool rules, and path-scoped `Edit(~/.claude/**)` /
`Edit(~/.claude/projects/**)` rules so routine agent work does not stall.
Only `Edit(path)` rules are matched by Claude Code's file-permission checks -
path-scoped `Write(path)` rules are silently ignored and trigger a startup
warning, so the installer no longer adds them and migrates them out of
existing `~/.claude/settings.json` files that still have them (`legacy_allow`
in the same script). The strip only runs when the bare `Write` rule is
already present in the pre-migration config; if it is absent, the scoped
rule is left in place. This does not change effective permissions either
way - bare `Write` is added by the recommended-merge regardless, and the
scoped rule is inert - it only avoids the installer editing a config a
user may have deliberately narrowed without their input. The trade-off is
that Claude Code's startup warning about the inert scoped rule persists
for that edge case.

## Hooks

DinoStack ships hooks in [`hooks/`](../hooks/). PreToolUse and Stop hooks are
wired into `~/.claude/settings.json` by the installer; `pre-commit` is a git
hook installed separately:

- [`enforce-askuserquestion-default.py`](../hooks/enforce-askuserquestion-default.py)
  - PreToolUse; denies a co-equal multiple-choice prompt with no recommended default.
- [`enforce-background-spawn.py`](../hooks/enforce-background-spawn.py)
  - PreToolUse (Task/Agent); (a) enforces background-by-default on both `Task` and `Agent`
  with an asymmetric rule - `Task` denies unless `run_in_background: true`; `Agent` denies only
  an explicit `run_in_background: false` (absent allows, since Agent backgrounds by default);
  (b) sentinel suppression: denies Task/Agent spawns and `oh-my-claudecode:*` Skill calls
  when `.agentic/teamrun/.active` is live. Foreground-exempt agents (wrap-ticket) bypass both.
- [`enforce-orchestrator-singularity.py`](../hooks/enforce-orchestrator-singularity.py)
  - PreToolUse; denies any `Task` spawn issued from a subagent context; disable via
  `AE_SINGULARITY_GUARD_DISABLE=1`.
- [`enforce-no-abdication.py`](../hooks/enforce-no-abdication.py) - Stop hook;
  detects three shapes in the final assistant message - a permission-seeking interrogative,
  a surface-and-proceed default announced and then not acted on, or a prose co-equal
  ballot in an `## Operator decisions` block - and blocks the stop, injecting a
  directive; requires `abdication_guard_enabled: true` in `.agentic/config.json`
  (absent/malformed config = guard does not run; the shipped template and
  `/ds-init-project` set it); set to `false` to opt out once enabled;
  disable via `AE_ABDICATION_GUARD_DISABLE=1`.
- [`enforce-turn-shape.py`](../hooks/enforce-turn-shape.py) - Stop hook;
  checks the conductor's final turn against the fixed-shape/warranted-turn
  rule. As of DS-156 this is NOT uniformly advisory: `_execution_prose_flag`
  (a non-Answer turn's structural shape) is BLOCKING and can block the stop,
  injecting a directive to reshape the turn; `_answer_relevance_flag`
  (opening-preamble/closing-recap phrasing on an Answer turn) remains
  advisory-only and only logs a finding. **DS-156 CONTRACT, NOT YET SHIPPED:**
  the blocking behavior above is Unit 2's implementation target
  (`content/references/conductor-turn-format.md`); the currently shipped
  hook remains uniformly advisory. Controlled by
  `turn_shape_guard_enabled` in `.agentic/config.json`, default `true`
  (absent key resolves to on - the inverse of the abdication guard's
  fail-open-to-inactive default; the risk profile is now closer to
  symmetric with the abdication guard than before DS-156, since the
  structural check can block); set to `false` to opt out of both; disable
  per-session via `AE_TURN_SHAPE_GUARD_DISABLE=1`. Unlike its
  sibling enforcers, its `~/.claude/settings.json` registration is **guarded**
  (`test -f ... && python3 ... || exit 0`), so a reverted PR removing the
  script cannot leave a dangling blocking Stop entry.
- [`enforce-worktree-read.py`](../hooks/enforce-worktree-read.py)
  - PreToolUse (Read); denies a worktree-isolated subagent's `Read` when the
  target resolves inside the primary checkout instead of the agent's own
  worktree; never fires on a conductor (main-session) read; disable via
  `AE_WORKTREE_READ_GUARD_DISABLE=1`.
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
parallel Workers from contaminating one shared tree. It scopes **git state**,
and, as of `enforce-worktree-read.py`, a subagent's `Read` calls - it does not
isolate any other host filesystem access or the network. Leave isolation on;
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

## Controlling token spend (right-sizing review)

The dominant driver of token cost is the Elevated classification. Nearly every
code edit with behavioral effect, new file, multi-file change, and config change
trips Elevated. Each Elevated task fans out to a Worker + Skeptic (and often an
architect, orchestration-planner, and QA engineer too), each re-reading context.
Small tasks pay the full pipeline.

The **risk profile** is the primary lever for cutting that cost. Moving from
`strict` or `default` toward `relaxed` reclassifies more small work as Low
(conductor direct action, no spawns), which removes the Worker + Skeptic
overhead entirely. See the [Risk profiles](#risk-profiles) section above for
the full list of which signals shift at each level.

### Tradeoff

Use `relaxed` for solo work and trusted-repo iteration to reduce
token spend; accept that small behavioral edits skip independent Skeptic review.
Keep `default` or `strict` where a mistake costs time or data - shared repos,
security-sensitive paths, or any work that is hard to revert. The
[recommended configs table](#risk-profiles-and-recommended-configs) maps
common contexts to sensible starting points.
