# Threat model

A lightweight threat model for running DinoStack agents. It names the actors,
the assets worth protecting, and the realistic scenarios, then maps each to its
existing mitigation and the residual gap. It is intentionally STRIDE-flavored
rather than a formal STRIDE matrix.

This document is part of the safety set:
[SAFETY.md](../SAFETY.md) (posture and checklist),
[safe-configuration.md](safe-configuration.md) (how to lock things down),
[secrets-and-permissions.md](secrets-and-permissions.md) (where secrets live).
Report flaws via [SECURITY.md](../SECURITY.md).

## Scope

This models the **framework's own surface**: the agent loop, the permission
configuration, the hooks, and the git/worktree machinery DinoStack ships. It
does not model the security of any product you build with it, nor general LLM
model behavior unrelated to a reproducible framework flaw (out of scope per
[SECURITY.md](../SECURITY.md)).

## Actors

- **The operator** - the human running the session. Trusted, but fallible
  (can misconfigure permissions, approve a bad plan, paste a secret).
- **The agent** - the LLM and its subagents. Acts with the operator's full
  shell privileges. Not adversarial by design, but steerable by untrusted
  input and capable of mistakes.
- **Untrusted content** - files, web pages, issue text, or dependency code the
  agent reads. The injection vector.
- **A third party on a shared repo** - another contributor whose code or PR the
  agent may consume or build on.

## Assets

- **The host** - filesystem, processes, and anything reachable on the network
  from the operator's machine.
- **Secrets** - API keys, tokens, and `.claude/settings.local.json` contents.
- **Repository integrity** - branch history, the working tree, and what lands
  in a commit or PR.
- **The supply chain** - the framework's own dependencies and any it installs.

## Scenario table

| Scenario | Asset | Existing mitigation (path) | Residual gap |
|---|---|---|---|
| **Prompt injection drives a destructive command.** Untrusted content steers the agent to run a damaging shell command. | Host, repo integrity | Deny-list blocks eight destructive patterns ([`.claude/install.sh`](../.claude/install.sh) ~736-743, listed in [safe-configuration.md](safe-configuration.md#the-deny-list)); Elevated risk routes through Skeptic review ([content/sections/04-risk-classification.md](../content/sections/04-risk-classification.md)). | Deny-list is a finite pattern rail - a destructive action phrased outside the eight patterns is not blocked. Skeptic review is a process control, not an automated tool-call gate. |
| **Secret exfiltration.** A secret the agent legitimately reads is sent over the network or written somewhere unintended. | Secrets | Secrets live in gitignored `.claude/settings.local.json` ([content/rules/conventions.md](../content/rules/conventions.md)); telemetry has a documented no-secrets field boundary ([content/sections/09-events-log.md](../content/sections/09-events-log.md)). | The telemetry no-secrets boundary is a **design intent**, not runtime-enforced redaction. Nothing prevents an agent that has read a secret from transmitting it. Scope credentials tightly ([secrets-and-permissions.md](secrets-and-permissions.md)). |
| **Supply-chain compromise via a dependency.** A malicious or compromised package the framework uses or installs runs code. | Supply chain, host | DCO sign-off on commits ([CONTRIBUTING.md](../CONTRIBUTING.md)); automated secret/code scanning (CodeQL, gitleaks, Scorecard) is being added - see DS-20 / PR #239. | Until DS-20 lands and runs on `main`, there is no automated scanning gate in CI. Pin and review dependencies you add. Re-check [`.github/workflows/`](../.github/workflows/) for current coverage. |
| **Worktree / commit contamination.** A Worker stages the conductor's untracked files, or parallel Workers corrupt a shared tree, polluting a PR. | Repo integrity | Mandatory worktree isolation for every implementer spawn ([content/sections/11-worktree-lifecycle.md](../content/sections/11-worktree-lifecycle.md)). | Isolation scopes git state only. A Worker can still write paths outside the worktree on the host. Review PR file lists before merge. |
| **Host damage outside the repo.** The agent reads, writes, or deletes files elsewhere on the machine, or hits the network. | Host | Deny-list catches some destructive forms (`rm -rf`, `sudo rm`, `dd if=`); risk classification flags shared-state and irreversible work. | No layer sandboxes the host filesystem, network, or processes. The agent runs with the operator's shell privileges. Run sensitive sessions in a constrained environment. |
| **Hook tampering or bypass.** The enforcement or pre-commit hooks are disabled, edited, or simply skipped. | Repo integrity, process controls | PreToolUse hooks enforce background-spawn and AskUserQuestion defaults ([`hooks/enforce-background-spawn.py`](../hooks/enforce-background-spawn.py), [`hooks/enforce-askuserquestion-default.py`](../hooks/enforce-askuserquestion-default.py)). | All hooks **fail open** by design: a parse error degrades to no-enforcement. The [`pre-commit`](../hooks/pre-commit) hook is **skipped inside worktrees** and is a build/reminder hook, not a fail-closed validator. Hooks are Claude Code only and are wired by `install.sh`; an agent with edit access can modify them. |

## Cross-cutting residual gap

The unifying gap across every row: **the agent runs with the operator's
privileges and is not sandboxed.** The deny-list, risk-and-Skeptic review, and
worktree isolation each lower the odds or the blast radius of a bad action, but
none removes the agent's ability to act. The operator remains the last line of
review. See [SAFETY.md](../SAFETY.md) for the run-safely checklist and
[safe-configuration.md](safe-configuration.md) for the configuration knobs that
tighten each layer.
