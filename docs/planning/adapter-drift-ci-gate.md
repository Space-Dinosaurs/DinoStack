# Brief: Advisory CI adapter-drift gate

**Problem:** `content/` changes developed in a git worktree merge with stale per-harness adapter outputs because `hooks/pre-commit` self-skips inside worktrees (this happened: PR #101 shipped content-only, required remediation PR #102). `.pi/` is a second standing drift hole - tracked but never wired into the pre-commit build/stage lists, and `.pi/build.sh` has no stale-prune so a deleted `content/commands/*.md` leaves an undetected orphan. Nothing surfaces this drift before merge.

**Success criteria:**
- Every PR runs a CI check that rebuilds all 8 adapters and fails (red, advisory) when committed adapter output differs from `content/`
- `.pi` is wired into `hooks/pre-commit` (build + stage) so local main-tree commits keep it in sync
- `.pi/build.sh` prunes orphan `.pi/prompts/*.md` whose source `content/commands/*.md` was deleted (closes the false-negative)
- The advisory-only scope (no required status check on this private free-plan repo) is recorded as an explicit decision

**Non-goals:**
- Hard merge-blocking / required status check (descoped: private free-plan repo cannot set branch protection; operator-accepted advisory)
- Auditing/fixing stale-prune across the other 7 build scripts (pre-existing, deferred follow-up)
- Any change to the worktree-skip block, HTML-stamp block, `methodology-drift.yml`, or `check-methodology-drift.sh`

**Constraints:** No `gh api`/branch-protection step anywhere. CI `git diff` MUST be the scoped form `git diff --exit-code -- .claude .codex .cursor .gemini .kimi .opencode .omp .pi` (prior-Skeptic-mandated load-bearing positive scoping, not bare diff). `.pi/build.sh` prune scoped only to `$PROMPTS_DST/*.md` (must not touch the 4 symlinks or `$SKILL_DST` outputs). `SKILL.frontmatter.yaml` is a tracked input - never staged. All 4 units ship in ONE PR.

**Verification:** (1) `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/adapter-sync.yml'))"` parses clean; (2) `bash -n hooks/pre-commit` exits 0 AND a staged-commit dry-run on a throwaway branch where `git diff --cached --name-only | grep -q '^\.pi/'` returns TRUE; (3) `bash -n .pi/build.sh` exits 0, `bash .pi/build.sh` run twice from clean tree yields no git diff (idempotent), and deleting a `content/commands/*.md` then running `.pi/build.sh` removes the matching `.pi/prompts/<name>.md` and prints the removal line; (4) MEMORY.md `## Decisions` entry present, dated 2026-05-18, referencing the `check-adapter-sync` job and the public/Pro upgrade path; (5) running the full 8-build sequence then the scoped `git diff --exit-code` is green on a synced tree and red when an orphan/drift is uncommitted.

**QA criteria:**
```yaml
qa_criteria:
  qa_skip: config-only
  qa_skip_rationale: "Pure CI/build-infra change (new GitHub Actions workflow, pre-commit hook wiring, build-script prune loop, MEMORY.md decision record); no runtime-observable application surface. Verification is shell/CI dry-run, not browser/api."
  scenarios: []
  manual_smoke: "none"
```

**Linked artifacts:** architect-plan: inline Revision 2 (this session, conductor-amended per Skeptic fix pass 1); orchestration: inline JSONL (4 units: memory-decision-record [Low], adapter-sync-workflow [Elevated], pi-buildsh-prune [Elevated], precommit-pi-staging [Elevated])
