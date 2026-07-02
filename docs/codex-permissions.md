# Codex Permissions

For trusted DinoStack work, configure Codex so the agent can run the full workflow without stopping at every tool call:

```toml
sandbox_mode = "danger-full-access"
approval_policy = "never"
```

These are top-level keys in `~/.codex/config.toml`.

This posture is intentionally high-trust. It lets Codex run commands, edit files, create worktrees, run checks, and operate the named engineer/Skeptic workflow without permission prompts that stall background work. It is appropriate when you are working in a trusted repository on a machine where you are comfortable letting Codex act with your user permissions.

The tradeoff is that this is not a sandbox boundary. A mistaken or malicious instruction can affect files outside the current checkout, access networked resources available to your user, or run destructive commands. DinoStack's risk classification, conductor delegation rule, and Skeptic review reduce engineering mistakes; they do not replace operating-system isolation.

Verify the config after editing:

```bash
codex --strict-config doctor
```

Use a stricter posture for untrusted repositories, dependency triage on unfamiliar code, security research, copied prompts from unknown sources, or any session where you do not want Codex to have broad filesystem and command access. In those cases, prefer a workspace sandbox and explicit approvals even though the workflow will require more manual intervention.
