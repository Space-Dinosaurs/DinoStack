# evals

Internal eval harness for component-level evals of named agents and slash commands, supporting the self-improving-harness roadmap in `docs/planning/p2-self-improving-harness.md`.

## Stack
- Python 3.11, pyyaml (>=6.0), stdlib only otherwise
- Claude CLI (`claude -p`) as the model invocation shell-out
- git worktrees for Tier 2 filesystem isolation

## Key Conventions
- Read `evals/LEARNINGS.md` before starting any new component eval - it captures hard-won lessons on enum-vocabulary exposure, prompt telegraphing, vacuous dimensions, and isolation-mechanism alignment.
- The runner shells out to `claude -p`; it does not use an SDK. Two invocation modes:
  - Agent mode: two-level Task-spawn pattern (outer `claude -p` dispatches a Task to the named subagent).
  - Command mode: inline the slash-command body as the `-p` prompt content. `claude -p "/<slash>"` does NOT dispatch slash commands under a redirected HOME.
- Isolation tiers:
  - Tier 1: read-only, no Bash, no network (Skeptic, Conductor).
  - Tier 2: git worktree + redirected HOME, write-enabled (init-project).
  - Tier 3: Docker container isolation with `Tier3Docker` in `evals/runner/isolator.py` — build-once cache, force_rebuild via `docker rmi -f`, `--network none`, `--read-only` rootfs, held-out tests mounted at `/scoring/tests:ro`. Required for skill-comparison and Worker eval.
- `fixture_hash` normalizes to a semantic JSON subset, not raw YAML bytes, to avoid pre-commit secret-scanner false-positives on sha256 substrings.
- TSV results under `evals/results/` are committed; `.runlog.jsonl` files and `.worktrees/` are gitignored.
- Overfitting Rule (`evals/OVERFITTING-RULE.md`) gates any `content/` edit motivated by eval scores: "would this edit still matter if the fixture disappeared?"

## Gotchas
- Pre-commit secret-scanner false-positives on sha256 substrings as "Cloudflare API Token". Rotate fixture content via prompt-neutral mechanisms (trailing blank lines, block-scalar style toggle) rather than changing hash inputs.
- Mid-run auth 401s during long runs (40+ min wall clock). The runner has no retry policy - kill and re-run manually if a run aborts.
- `claude -p "/<slash>"` does not dispatch slash commands under a redirected HOME (user-scope commands are not discoverable). Use command-mode inline-body invocation instead.
- TSV `description` column `[raw-prompt]` prefix applies only to unexpected fallbacks on agent-mode invocations. Command-mode runs are raw-prompt by design and must not be prefixed.
- Tier 2 HOME redirect broke Claude CLI auth (macOS keychain / Linux `.credentials.json`) until PR #12. Narrow auth-preservation symlinks in `evals/runner/isolator.py` preserve credentials. If command-mode evals score at the 0.2 floor (forbidden_credit only), suspect auth - verify isolator symlinks.
- Auto-harness dimension signal (`evals/auto/loop.py:_build_dimension_signal`, PR #49) returns `_NO_SIGNAL_LINE` for scorers emitting semantically-rich nested dicts (`tp_recall.matched[*].credit`, `signal_discipline` tier, etc.). Only ~4 components currently receive a usable signal. Per-component extractors are the next unlock.
- Mean-of-medians (not median) is the auto-harness keep-metric since PR #41. Median was blind to single-fixture improvements when ≥half fixtures were at ceiling 1.0.
- Skeptic FP-cap recalibration plan (architect output, 2026-05-01) was rejected - proposed `0.5 -> 0.75` multiplier change has zero effect on the actual TSV patterns observed for cited cap-fixtures. Restart with per-fixture math projection table before any retry.
