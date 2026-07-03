# Codex Permissions

For trusted DinoStack work, configure Codex so the agent can run the full workflow without stopping at every tool call:

```toml
sandbox_mode = "danger-full-access"
approval_policy = "never"
```

These are top-level keys in Codex config. Put them in `~/.codex/config.toml` when you want the trusted-work posture as your personal default, or in a trusted project's `.codex/config.toml` when you want the posture scoped to that repo or subfolder.

Codex resolves config in layers. CLI flags and `--config` overrides win first; trusted project `.codex/config.toml` files win over profile files and the user-level `~/.codex/config.toml`; system config and built-in defaults are lower precedence. If a project is marked untrusted, Codex skips project-scoped `.codex/` layers, including project-local config, hooks, and rules.

The DinoStack Codex installer only manages user-level adapter wiring: global AGENTS.md, named agents, hooks, and `codex_hooks = true` under `[features]` in `~/.codex/config.toml`. It does not write project-level `.codex/config.toml`; add that file yourself when a single repo needs different sandbox, approval, model, provider, or MCP settings.

This posture is intentionally high-trust. It lets Codex run commands, edit files, create worktrees, run checks, and operate the named engineer/Skeptic workflow without permission prompts that stall background work. It is appropriate when you are working in a trusted repository on a machine where you are comfortable letting Codex act with your user permissions.

The tradeoff is that this is not a sandbox boundary. A mistaken or malicious instruction can affect files outside the current checkout, access networked resources available to your user, or run destructive commands. DinoStack's risk classification, conductor delegation rule, and Skeptic review reduce engineering mistakes; they do not replace operating-system isolation.

Verify the config after editing:

```bash
codex --strict-config doctor
```

Use a stricter posture for untrusted repositories, dependency triage on unfamiliar code, security research, copied prompts from unknown sources, or any session where you do not want Codex to have broad filesystem and command access. In those cases, prefer a workspace sandbox and explicit approvals even though the workflow will require more manual intervention.
