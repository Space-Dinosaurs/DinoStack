# Architect Plan: bootstrap.sh + location-aware /update-agentic-engineering

> Source: architect agent (revision 2). Persisted by conductor for Skeptic review and audit.
> Canonical repo: `Solara6/agentic-engineering` (HTTPS `https://github.com/Solara6/agentic-engineering.git`, SSH `git@github.com:Solara6/agentic-engineering.git`, raw `https://raw.githubusercontent.com/Solara6/agentic-engineering/main/bootstrap.sh`).

## Approach

Create `bootstrap.sh` at repo root as a public `curl | bash`-installable entrypoint that clones the repo, delegates to `.claude/install.sh`, and records the resolved install path to `~/.agentic/agentic-engineering-config.json`. Simultaneously patch `content/commands/update-agentic-engineering.md` to resolve the repo location from that config key (`repo_dir`) before falling back to the legacy `~/agentic-engineering` default, then regenerate all adapter build artifacts so the `adapter-sync` CI gate passes.

## Codebase context

### `content/commands/update-agentic-engineering.md` - the operational hardcodes
- Line 36: `cd ~/agentic-engineering && git fetch origin` (Step 0 preflight)
- Line 68: `bash ~/agentic-engineering/.claude/build.sh` (Step 3 build command)
- Lines 5, 8, 10: prose references (documentational; classified leave-as-default)

### `.claude/install.sh` config-write pattern
python3 read-merge-write: read existing JSON, update only specific keys, write back; handles missing file/dir; swallows non-fatal errors. Mirror this for `~/.agentic/agentic-engineering-config.json`.

### Adapter build system
- `adapter-sync.yml` runs 8 build scripts: `.claude`, `.cursor`, `.codex`, `.gemini`, `.kimi`, `.opencode`, `.omp`, `.pi` build.sh; CI does `git diff --exit-code` across adapter dirs.
- `.hermes/build.sh` exists but is NOT in the CI gate (regen anyway for correctness).
- All build scripts self-locate via `REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"`.
- `content/commands/*.md` get a prerequisite blockquote prepended by `.claude/build.sh`. Engineer must NOT hand-edit `.claude/commands/update-agentic-engineering.md` - edit `content/` source then rebuild.
- `.claude/skills/agentic-engineering/references/` are hardlinks into `content/references/` - no rebuild for those.

### `~/agentic-engineering` hardcode sweep (classified)
Only `content/commands/update-agentic-engineering.md` lines 36, 68 are class (a) must-become-config-aware. All other hits across `content/sections/**`, `content/references/**`, `content/agents/**`, other `content/commands/**`, `README.md`, `CONTRIBUTING.md` are class (b) documented-default (prose/concept, resolved via symlinks at runtime) - deliberately untouched.

### Resolution snippet (instructed in updated Step 0 / Step 3)
```bash
AE_REPO_DIR=""
AE_CONFIG="$HOME/.agentic/agentic-engineering-config.json"
if [[ -f "$AE_CONFIG" ]]; then
  # SKEPTIC-MINOR-1 fix: pass the config path via argv (sys.argv[1]), NOT
  # interpolated into the python string literal. Mirrors the safer
  # ae_write_config variant in .claude/install.sh, avoids quote/backslash breakage.
  AE_REPO_DIR="$(python3 -c "
import json, sys
try:
    with open(sys.argv[1]) as f:
        print(json.load(f).get('repo_dir', ''))
except Exception:
    print('')
" "$AE_CONFIG" 2>/dev/null)"
fi
# SKEPTIC-MINOR-2 fix: use rev-parse, not [[ -d .git ]]. In a git worktree
# .git is a FILE, not a dir; -d would wrongly discard a valid repo_dir.
if [[ -z "$AE_REPO_DIR" ]] || ! git -C "$AE_REPO_DIR" rev-parse --git-dir >/dev/null 2>&1; then
  AE_REPO_DIR="$HOME/agentic-engineering"
fi
```
Step 0 -> `cd "$AE_REPO_DIR" && git fetch origin`. Step 3 -> `bash "$AE_REPO_DIR/.claude/build.sh"`.

## Data model
`~/.agentic/agentic-engineering-config.json` extended additively with `{"repo_dir": "/absolute/path/.../agentic-engineering"}`. Pre-existing keys (adapter selections from update.sh) preserved.

## Interface

`bootstrap.sh`:
- `curl -fsSL https://raw.githubusercontent.com/Solara6/agentic-engineering/main/bootstrap.sh | bash`
- `AE_DEST_DIR` env override; default `$(pwd)/agentic-engineering`; normalized to absolute.
- **SKEPTIC-CRITICAL fix - clone branch MUST be written so the SSH fallback is reachable under `set -euo pipefail`.** A bare sequential `git clone https://...` followed by `git clone git@...` aborts on the first failure because `set -e` traps the non-zero exit before the fallback line. The engineer MUST use an explicit conditional so the HTTPS failure is caught, not fatal:
  ```bash
  if ! git clone "$HTTPS_URL" "$AE_DEST_DIR"; then
    echo "HTTPS clone failed (repo may be private); trying SSH..." >&2
    if ! git clone "$SSH_URL" "$AE_DEST_DIR"; then
      echo "Both HTTPS and SSH clone failed. If the repo is private, ensure SSH access is configured." >&2
      exit 2
    fi
  fi
  ```
  `HTTPS_URL=https://github.com/Solara6/agentic-engineering.git`, `SSH_URL=git@github.com:Solara6/agentic-engineering.git`. The `if ! cmd` form is the canonical `set -e`-safe trap. A `cmd || fallback` form is also acceptable but the `if !` form is mandated here for clarity in the spec; engineer may use either as long as the HTTPS failure is demonstrably non-fatal and the SSH path is reached (verified by test scenario 6).
- **SKEPTIC-MINOR-3 fix - parent-dir precreation.** Before clone, `mkdir -p "$(dirname "$AE_DEST_DIR")"` so a multi-level `AE_DEST_DIR` (e.g. `/tmp/new/deep/agentic-engineering`) does not fail with "parent does not exist". If `mkdir -p` itself fails (unwritable), exit 1 with an actionable message naming the unwritable parent.
- Delegate `bash "$DEST/.claude/install.sh" "$@"` (positional passthrough; `"$@"` is `set -u`-safe with zero args - Skeptic-confirmed, do NOT introduce an `INSTALL_ARGS` array).
- Dirty-tree (existing dest): warn, continue.
- Exit codes: 0 success, 1 validation error (incl. unwritable AE_DEST_DIR parent), 2 clone failure (both HTTPS and SSH), 3 install.sh failure.
- Success message: updates via `cd <dest> && ./update.sh` OR `/update-agentic-engineering` (now location-aware).

`content/commands/update-agentic-engineering.md`: Step 0/Step 3 use resolved `AE_REPO_DIR`; backward-compatible fallback to `~/agentic-engineering`.

## Implementation units

### Unit A - bootstrap.sh + config write + README (independent)
Files: `bootstrap.sh` (new), `README.md` (modify).
1. Create `bootstrap.sh`, `set -euo pipefail`, manifest header, normalize AE_DEST_DIR to absolute, `mkdir -p "$(dirname "$AE_DEST_DIR")"` (exit 1 if unwritable), dirty-tree check, **`set -e`-safe conditional HTTPS->SSH clone** (the `if ! git clone ...` structure mandated in the Interface section - bare sequential clones are a Critical defect), delegate `bash "$DEST/.claude/install.sh" "$@"`, additive python3 config write of `repo_dir` passing the config path via `sys.argv[1]` not string interpolation (create `~/.agentic/` if absent, non-fatal on failure), success summary, exit codes 0/1/2/3.
2. README: add one-liner install section, SSH manual alternative, `AE_DEST_DIR` doc.

### Unit B - slash-command patch + adapter regen (independent of A; parallelizable)
Files: `content/commands/update-agentic-engineering.md` (modify), all regenerated adapter outputs.
3. Edit `content/commands/update-agentic-engineering.md`: Step 0 resolution snippet + `cd "$AE_REPO_DIR"`; Step 3 `bash "$AE_REPO_DIR/.claude/build.sh"`; update prose lines 5/8/10 to describe runtime resolution.
4. Run all 9 build scripts (`.claude .cursor .codex .gemini .kimi .opencode .omp .pi .hermes`), confirm each exits 0.
5. Verify `git diff --exit-code -- .claude .codex .cursor .gemini .kimi .opencode .omp .pi` clean.
6. Commit content source + regenerated adapters together.

Units A and B touch non-overlapping files - parallelizable in separate worktrees.

## QA criteria
```yaml
qa_criteria:
  qa_skip: pure-backend-library
  qa_skip_rationale: "All changes are shell scripts and markdown documentation with no browser or UI surface; verification is via local shell execution and git diff checks."
  scenarios: []
  manual_smoke: none
```

## Per-unit verification

### Unit A (file:// bare-repo local tests)
1. Happy path default dest -> clone at `$(pwd)/agentic-engineering`, config `repo_dir` set, install.sh symlinks present.
2. Custom dest via `AE_DEST_DIR` -> installs there, absolute path recorded.
3. Relative `AE_DEST_DIR` -> recorded path is absolute.
4. Dirty tree existing dest -> warn, continue, no abort.
5. Additive config write -> pre-existing keys preserved.
6. HTTPS fail -> SSH fallback attempted.
7. Both clone methods fail -> exit 2.

### Unit B
**SKEPTIC-MAJOR fix - test precondition (mandatory):** Unit B's resolution tests MUST hand-create a temporary `~/.agentic/agentic-engineering-config.json` (or point `AE_CONFIG` at a temp fixture path) and a throwaway git repo for the "valid path" case. Unit B tests MUST NOT depend on Unit A having been built, shipped, or run - the two units are parallelizable precisely because B is verified against a hand-crafted config fixture, not A's runtime output. Each test case below backs up any real `~/.agentic/agentic-engineering-config.json` first and restores it after, OR runs the resolution snippet with `AE_CONFIG` overridden to a temp file (preferred - no mutation of the real user config).
1. `repo_dir` present + path is a real git repo (hand-create `git init` temp dir) -> resolves to that custom path.
2. No config file (temp `AE_CONFIG` points at nonexistent path) -> fallback `~/agentic-engineering`.
3. Config present, no `repo_dir` key (hand-write `{"other":"x"}`) -> fallback.
4. `repo_dir` -> non-git path (hand-write a path to an empty temp dir) -> fallback (verifies the `git rev-parse --git-dir` guard, not the old `-d .git` check).
5. Adapter-sync gate: 8 build scripts then `git diff --exit-code -- .claude .codex .cursor .gemini .kimi .opencode .omp .pi` exits 0.
6. `diff content/commands/update-agentic-engineering.md .claude/commands/update-agentic-engineering.md` shows only prepended prerequisite blockquote.

## Acceptance criteria
1. One-liner clones, runs install.sh, writes `repo_dir`.
2. `AE_DEST_DIR=/custom bash bootstrap.sh` installs to `/custom/agentic-engineering`, records absolute path.
3. `repo_dir` write additive (pre-existing keys preserved).
4. After custom-path install, `/update-agentic-engineering` resolves to custom path.
5. Existing install w/o `repo_dir` -> `~/agentic-engineering` (backward-compat).
6. `repo_dir` not a git repo -> fallback.
7. 8 build scripts + `git diff --exit-code` adapter dirs exits 0.
8. `.claude/commands/update-agentic-engineering.md` build artifact has prereq prefix + patched content.
9. `shellcheck bootstrap.sh` exits 0, no warnings.
10. Bootstrap success message references both update methods, no stale limitation note.
11. Exit codes 0/1/2/3 as specified.

## Trade-offs / known limitations
- `repo_dir` stored in `~/.agentic/agentic-engineering-config.json` (not `~/.claude/agentic-engineering.json`) - avoids coupling with activation-mode file; the `~/.agentic/` file already exists for update.sh adapter selections.
- Class (b) prose references intentionally untouched (resolved via symlinks at runtime; patching = cosmetic churn, high regen cost, zero functional gain).
- Resolution snippet inline (no shell-include mechanism in an LLM-loaded command file); 12 lines acceptable.
- python3 not jq (jq not guaranteed; python3 is the established codebase pattern).
- bootstrap config-write failure non-fatal -> `/update-agentic-engineering` falls back to `~/agentic-engineering` for a custom install (edge case: read-only home).
- `.hermes/build.sh` not in CI gate; regen for correctness, CI won't catch drift.
- `AE_REPO_DIR` resolved once in Step 0, reused Step 3 (same agent context within one command invocation - true by design).

## Open questions
None.
