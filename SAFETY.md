# Safety

This document describes how DinoStack tries to keep agent work from causing
harm, and - just as important - where those protections stop. It is the fuller
companion to the short [Safety model](README.md#safety-model) section in the
README. To report a suspected framework-level safety or security flaw, see
[SECURITY.md](SECURITY.md).

## Posture: a rail, not a boundary

DinoStack runs LLM agents with real tool access (Bash, file writes, git). The
framework is a safety **rail**, not a complete security **boundary**. It steers
agents away from common destructive mistakes and forces high-risk work through
review, but it does not sandbox the agent and cannot guarantee an agent is
unable to do damage. Treat every protection here as defense in depth, and review
what agents actually do - especially on shared state and irreversible
operations.

## The three defense layers

None of these is a sandbox. Each reduces the chance or blast radius of a bad
action; none removes it.

### 1. The deny-list (a finite pattern rail)

The recommended Claude Code permission setup pairs `bypassPermissions` mode with
a deny-list that blocks eight destructive command patterns (force push,
`rm -rf`, hard reset, and so on). It is configured by
[`.claude/install.sh`](.claude/install.sh) and the full listing lives in
[docs/safe-configuration.md](docs/safe-configuration.md#the-deny-list). The deny-list
matches **specific command patterns**. A destructive action expressed in a form
the patterns do not cover is not blocked. It is a rail against the common cases,
not a comprehensive filter.

### 2. Risk classification plus Skeptic review

The methodology classifies every task as Trivial, Low, or Elevated (see
[content/sections/04-risk-classification.md](content/sections/04-risk-classification.md)).
Elevated work - any behavioral code change, anything touching auth, secrets,
payments, irreversible operations, or shared state - is implemented by a Worker
and then reviewed by an independent Skeptic before it is accepted (see
[content/sections/02-delegation.md](content/sections/02-delegation.md)). This is
a process control. It depends on the conductor classifying honestly and the
Skeptic catching the problem; it is not an automated gate on the agent's tool
calls.

### 3. Worktree isolation

Concurrent implementer agents run in isolated git worktrees branched from
`main`, so a Worker cannot stage or commit the conductor's untracked files into
its own PR, and parallel Workers do not contaminate each other's working tree
(see
[content/sections/11-worktree-lifecycle.md](content/sections/11-worktree-lifecycle.md)).
Isolation scopes git state. It does not isolate the filesystem, the network, or
anything outside the repo - an agent in a worktree can still read and write
paths elsewhere on the host.

## What this does NOT protect against

- **Destructive commands the deny-list patterns do not match.** The list is
  finite; novel phrasings get through.
- **Anything outside the repo.** No layer sandboxes the host filesystem,
  network, or processes. An agent can touch files anywhere your shell user can.
- **Secret misuse.** A secret an agent legitimately reads (to call an API, run a
  test) can be sent over the network or written somewhere unintended. The
  framework's no-secrets telemetry boundary is a design intent, not an enforced
  guarantee - see
  [docs/secrets-and-permissions.md](docs/secrets-and-permissions.md) and the
  secret-exfiltration row in
  [docs/threat-model.md](docs/threat-model.md).
- **Prompt injection.** Untrusted content an agent reads can steer it toward an
  action you did not intend. Review still matters.
- **Hooks failing open.** The enforcement hooks
  ([`hooks/`](hooks/)) fail open by design: a parse error degrades to
  no-enforcement rather than blocking all work. The `pre-commit` hook is also
  skipped inside worktrees. Do not treat hook presence as a hard guarantee.

For the structured view of who can attack what and which gaps remain, read
[docs/threat-model.md](docs/threat-model.md).

## Run-it-safely checklist

- **Keep the deny-list configured.** Accept the recommended permissions during
  install, or merge the eight rules in manually
  ([docs/safe-configuration.md](docs/safe-configuration.md#the-deny-list)).
- **Match the risk profile to the context.** Use a stricter profile on shared or
  sensitive repos; see
  [docs/safe-configuration.md](docs/safe-configuration.md#risk-profiles-and-recommended-configs).
- **Never commit secrets into tracked config.** Secrets belong in
  `.claude/settings.local.json` (gitignored). See
  [docs/secrets-and-permissions.md](docs/secrets-and-permissions.md).
- **Scope credentials to the smallest blast radius.** Short-lived, least-
  privilege tokens limit what a misused secret can do.
- **Review irreversible and shared-state operations** before they land. The
  Skeptic loop helps, but you are the last reviewer.
- **Run sensitive work on a throwaway branch or checkout** when you are unsure
  what an agent will touch.
- **Rotate and report if a secret was ever committed.** See
  [SECURITY.md](SECURITY.md).

## Reporting

Suspected framework-level safety or security issues go through GitHub Security
Advisories - see [SECURITY.md](SECURITY.md) for scope, the reporting link, and
response times. General contribution guidance is in
[CONTRIBUTING.md](CONTRIBUTING.md).
