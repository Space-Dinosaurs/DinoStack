# Empirical findings: headless `claude --resume <id> -p "/wrap"` (G-HEADLESS-SPAWN)

*Operator-run real test, 2026-06-12. Raw log: `headless-log.json` (cwd; not committed). Decisive input for the v3 plan. Resolves Skeptic CRITICAL-1 and reshapes the daemon design.*

## What was tested
`claude --resume 7a7e502e-... -p "/wrap"` against a real prior session (`viva-voce`, a completed `/tech-groom VV-198` run), headless/no-TTY.

## Observed (from the log)
1. **Resume works.** Full prior conversation loaded; the session's context.md, ticket data, and prior architect/skeptic outputs were all present.
2. **Tool calls work headlessly.** `mkdir .agentic/wrap.lock`, `git branch/status/stash`, and Jira MCP calls all executed successfully in the `-p` run. (Tool execution was NOT the failure.)
3. **FATAL: `/wrap` is interactive.** The run hit a **stale `wrap.lock`** (pid 76924, ts 2026-05-19, ~3.5 weeks old). Per `/wrap`'s own pre-flight rule (wrap.md:79-85), it does NOT auto-remove a stale lock - it **aborts and asks the human**: "Want me to remove it and re-run `/wrap`? Reply yes." Headless, nothing answered -> the process exited having staged nothing and without resolving the lock.

## Conclusions (decisive)
- **The full interactive `/wrap` cannot be run headlessly.** It has multiple human-decision points (stale-lock prompt, "one thing needs your decision" closers, Skeptic-loop arbitration). Each is an indefinite hang in `-p` mode. The failure occurred BEFORE any subagent spawn - interactivity is the first and hardest blocker, deeper than the subagent question Skeptic CRITICAL-1 raised.
- **Stale locks are real and common** (a 3.5-week-old lock blocked this run). A daemon must manage the lock autonomously, not defer to a human.
- **A purpose-built, fully non-interactive, single-pass enrichment is required** (Option 1). Not a fidelity preference - a feasibility requirement.

## Design implications for v3
1. **New non-interactive command `/wrap-deferred`** (or a daemon-mode flag on `/wrap`): never prompts; single model pass; reads the resumed transcript + live inputs and writes context.md / `.agentic/memory.md` / AGENTS.md directly. NO draft-Worker, NO Skeptic, NO compression (Part E), NO `/cleanup-worktrees`, NO `gh pr` enumeration (or all strictly optional + skipped). On any ambiguity it writes what it can and exits cleanly (marker -> done or leaves for retry); it NEVER asks.
2. **Daemon-managed lock.** The daemon acquires `wrap.lock` and AUTO-CLEARS locks older than the 30-min staleness window in code (the documented staleness rule, automated). It never emits the interactive stale-lock prompt. Still serializes with live sessions via the existing lock-awareness.
3. **CRITICAL-2 dissolves: no worktree, no copy-back, no merge (pending architect confirmation).** With a self-contained enrichment writing the 3 docs directly, the daemon can run in the MAIN project dir under its managed lock + loop-guard, writing outputs to their canonical locations. This removes worktree create/cleanup, the gitignored-output copy-back, and the (broken) "merge committed outputs to branch" step entirely. d4 (worktree + copy-back) is re-opened and likely simplified away. Architect to confirm whether any isolation remains warranted (the enrichment writes only `.agentic/` + AGENTS.md, serialized by the lock; it runs only for ENDED sessions).
4. **Hardened headless invocation:** `--permission-mode bypassPermissions --allowedTools "Read,Edit,Write,Glob,Grep,Bash(git *)" --max-turns N`, wrapped in a **timeout-and-kill** (the hang is exactly why). No `--bare` (skill/CLAUDE.md context needed). Optionally `--output-format stream-json --verbose` to observe completion.
5. All prior Skeptic findings still apply where relevant: MAJOR-2 (`reason:resume` loss path), MAJOR-3 (late-Stop `ready`->`pending` regression), MAJOR-4 (doc-sync `04-risk-classification.md` count), MAJOR-5 (per-session markers vs single-file race), MAJOR-1 (`CLAUDECODE` guard verification), Minors 1-4. CRITICAL-1 resolved by the non-interactive single-pass design (no subagent pipeline headless). CRITICAL-2 resolved by no-merge/main-dir.

## Note on fidelity (Brief amendment)
The deferred wrap is single-pass: no adversarial Skeptic review of its own draft, no compression of `.agentic/memory.md`/CLAUDE.md. Manual `/wrap` remains the full-fidelity path. This amends the Brief success criterion "produces the same outputs as a synchronous wrap" -> "produces a good-faith single-pass enrichment of the same three targets; full-fidelity (reviewed + compressed) output remains the manual `/wrap` path."
