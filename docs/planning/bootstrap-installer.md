# Brief: bootstrap.sh public installer + location-aware /update-agentic-engineering

**Problem:** New users cannot install agentic-engineering with a single command - they must know to clone the repo (SSH only), cd in, and ask the agent to install. There is no `curl | bash` install path. Separately, the `/update-agentic-engineering` command hardcodes `~/agentic-engineering`, so an install placed anywhere else cannot be updated via the in-session command.

**Success criteria:**
- A single public one-liner (`curl -fsSL https://raw.githubusercontent.com/Solara6/agentic-engineering/main/bootstrap.sh | bash`) clones the repo to `$(pwd)/agentic-engineering` (overridable via `AE_DEST_DIR`), runs `.claude/install.sh`, and records the resolved absolute install path to `~/.agentic/agentic-engineering-config.json` (`repo_dir` key, additive write).
- `/update-agentic-engineering` resolves its working repo from `repo_dir`, falling back to `~/agentic-engineering` when the key/file is absent or not a git repo (backward compatible for existing installs).
- `bootstrap.sh` is `set -euo pipefail`-safe, shellcheck-clean, with a reachable HTTPS->SSH clone fallback and exit codes 0/1/2/3; its success message names both update paths (`cd <dest> && ./update.sh` and `/update-agentic-engineering`) with no stale "won't work from custom location" note.
- The `adapter-sync` CI gate passes: all 8 gated adapters regenerated and committed alongside the `content/` source edit.

**Non-goals:**
- Making the repo public (operator decision, deferred - one-liner 404s until then; SSH fallback covers collaborators now).
- npm/Homebrew/release distribution, or token-gated private install.
- Rewriting class (b) prose `~/agentic-engineering` references across `content/**` (cosmetic; resolved via symlinks at runtime).

**Constraints:** Canonical repo `Solara6/agentic-engineering`. `install.sh` flag form is `--mode=opt-out` (equals). python3 (not jq) for JSON writes, mirroring the existing `.claude/install.sh` pattern. Must not break existing `~/agentic-engineering` installs. macOS bash 3.2 target (`"$@"` passthrough; no `INSTALL_ARGS` array).

**Verification:** Unit A - local `file://` bare-repo tests (default/custom/relative dest, dirty-tree warn, additive config write, HTTPS->SSH fallback, both-fail exit 2) + `shellcheck bootstrap.sh` exit 0. Unit B - resolution tests via `AE_CONFIG` temp-fixture override (repo_dir valid/absent/no-key/non-git-path, no mutation of real user config) + `bash .claude/build.sh .cursor/build.sh .codex/build.sh .gemini/build.sh .kimi/build.sh .opencode/build.sh .omp/build.sh .pi/build.sh` then `git diff --exit-code -- .claude .codex .cursor .gemini .kimi .opencode .omp .pi` exits 0. Integration Skeptic verifies the `repo_dir` key name + absolute-path/git-repo semantics are consistent across A's write and B's resolution snippet.

**QA criteria:**
```yaml
qa_skip: pure-backend-library
qa_skip_rationale: "Shell installer + markdown command/doc edits; no browser or UI surface. Verified via shell execution and git diff gates."
scenarios: []
manual_smoke: none
```

**Linked artifacts:** architect-plan: docs/planning/bootstrap-installer-architect-plan.md (Skeptic-approved); orchestration: 2 units (bootstrap-unit-a, bootstrap-unit-b), parallelizable, integration Skeptic, no AC coverage gaps.
