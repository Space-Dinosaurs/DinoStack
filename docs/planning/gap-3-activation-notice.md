# Gap 3: Activation Preflight First-Activation Notice (Revised, Iteration 3)

## Convergence note - iteration 3

Closes Skeptic findings from iteration 2 review.

**Majors closed:**
- **MAJOR 1 (`/agentic-disable` opt-in conflict writes inert marker):** Adopted alternative (a). When AGENTS.md contains an `opt-in` line, `/agentic-disable` exits non-zero with a specific error message naming path and line, instructing manual removal. New `--force` flag removes the opt-in line then appends opt-out atomically. No more inert opt-out writes. Reflected in API/interface design (`/agentic-disable behavior contract`, step 1) and in Acceptance criteria (#13a, #13b new).
- **MAJOR 2 (Execution mechanism unspecified):** Adopted option (ii) per `bin/agentic-cost` precedent. New `bin/agentic-status` and `bin/agentic-disable` Python 3 stdlib scripts implement the logic; `content/commands/agentic-{status,disable}.md` are the user-facing command spec markdown files referencing the bin/ implementations. Manifest header required on the Python scripts; manifest dropped from the markdown specs (M4). Implementation steps updated.

**Minors closed:**
- **M1 (Step 6 renumbering grep):** Verified at plan time. Only `content/sections/01-activation-preflight.md` contains the affected "Step 5" - other matches in `content/commands/*.md` and `content/references/skeptic-protocol.md` refer to those files' own internal numberings and need no update. Step added to Implementation steps documenting the verification.
- **M2 (Build pipeline mirror):** Verified at plan time. `content/rules/agent-methodology.md` does NOT exist. `.claude/build.sh` invokes `scripts/build-methodology.sh` to assemble `content/sections/*.md` into `.claude/skills/agentic-engineering/METHODOLOGY.md`. Auto-mirrored; no hand-maintenance step needed. Old Implementation step 3 dropped; Codebase context updated.
- **M3 (Auto-create AGENTS.md rationale):** Adopted (b). Rationale stated verbatim in `/agentic-disable` behavior contract: "the user invoked `/agentic-disable`, an explicit opt-out signal; creating `AGENTS.md` with the marker is the minimum-blast-radius way to record that intent."
- **M4 (Manifest scope):** Manifest header required only on `bin/agentic-status` and `bin/agentic-disable` Python scripts. Markdown command specs `content/commands/agentic-{status,disable}.md` carry no manifest, matching `agentic-cost.md` precedent.
- **M5 (AC #17 wording):** Reworded. The TTY-suppression mechanism handles the eval case in principle, but plan-time verification that every eval invocation pipes stdout is out of scope. AC #17 now states the trigger condition and assigns verification responsibility to the eval harness contributor.

## Convergence note - iteration 2

[Preserved from iteration 2 for audit trail; superseded by iteration 3 above where overlapping.]

This iteration closes all findings from Skeptic review of iteration 1.

**Majors closed (iter 2):**
- **MAJOR 1 (Sentinel race in subagent contexts):** Closed in API/interface design ("Sentinel write contract") and Step 5 wording. Sentinel write is create-only (`open(path, 'x')` semantics or `link()` from tmp); notice print is gated on successful create.
- **MAJOR 2 (CI/headless + eval fixture contamination):** Closed by adopting alternative (a). When stdout is not a TTY OR `AGENTIC_QUIET=1`, the preflight skips BOTH the notice print AND the sentinel write.
- **MAJOR 3 (/agentic-disable blast radius undefined):** Closed in API/interface design under "/agentic-disable behavior contract" with explicit idempotency rule, exact insertion point, confirmation output, and `--global` JSON round-trip rule.

**Minors closed (iter 2):**
- M1: notice text uses `<preset or 'none'>`; preset literal `null` rendered as string `none` at print time.
- M2: `/agentic-status` and sentinel body comment state sentinel-deletion re-arms notice only.
- M3: filesystem errors writing `.agentic/.activated` are silently swallowed.
- M4: anti-collision check (vs Gap 2) section.

## Approach

Add a one-time first-activation notice to the activation preflight gated by a race-safe sentinel at `.agentic/.activated`, suppressed in non-TTY or `AGENTIC_QUIET=1` environments. Ship two helpers as Python 3 stdlib scripts in `bin/` (matching the `bin/agentic-cost` precedent): `agentic-status` (read-only resolver inspection) and `agentic-disable` (explicit opt-out, refuses on opt-in conflict unless `--force`). The `content/commands/agentic-{status,disable}.md` markdown files are the user-facing command specs that reference the bin/ implementations.

## Codebase context

- `content/sections/01-activation-preflight.md` is the canonical preflight spec (Steps 1-5 today). It is the single source of truth.
- `.claude/build.sh` invokes `scripts/build-methodology.sh` which assembles `content/sections/*.md` into `.claude/skills/agentic-engineering/METHODOLOGY.md`. Mirroring is fully automatic; the legacy `content/rules/agent-methodology.md` referenced in iteration 2 does not exist as a separate file.
- `~/.claude/agentic-engineering.json` shape (per Step 1): `{ "mode": "...", "profile": "...", "preset": "...", "set_at": "..." }`. Real user installs may carry only `mode` and `set_at`.
- Project-marker resolution: `AGENTS.md` at repo root, optionally imported via `CLAUDE.md` `@AGENTS.md`.
- `.agentic/` is the canonical project-local methodology dir; gitignored at template level.
- **`bin/` precedent (PR #29, `bin/agentic-cost`):** existing pattern is a Python 3 stdlib executable with a module manifest header, paired with a markdown command spec under `content/commands/` that documents usage and references the `bin/` implementation. The markdown spec carries no manifest (matches `agentic-cost.md`). New scripts follow this pattern.
- Existing markdown command specs under `content/commands/` are built into `.claude/commands/`, `.codex/commands/`, `.cursor/commands/` by `.claude/build.sh` and siblings.
- Eval harness (`evals/`) materializes fixtures via git worktrees.
- Docs site mirrors at `docs/agentic-engineering.html` and `docs/slides/*.md` (Marp). PR #28 docs sync rule applies.

## Data model

**Sentinel file: `.agentic/.activated`**
- Path: `<project_root>/.agentic/.activated`
- Format: plain text, ~3 lines.
- Contents (exactly):
  ```
  # agentic-engineering: first-activation notice has been shown for this project.
  # Deleting this file re-arms the notice only; it does not change activation state.
  # To opt out, use /agentic-disable.
  ```
- Lifecycle: created once on first successful activation in a TTY session with `AGENTIC_QUIET` unset; never updated; safe to delete (re-arms notice only).
- Gitignore: `.agentic/` is already excluded at the methodology template level; the sentinel is implicitly covered.

**AGENTS.md marker (existing):**
- Whole-line, case-insensitive: `agentic-engineering: opt-out` (or `opt-in`), with optional `- ` list prefix and surrounding whitespace.
- `/agentic-disable` appends this line at EOF (subject to opt-in conflict rules below).

**`~/.claude/agentic-engineering.json` round-trip (for `--global`):**
- Read existing JSON.
- Set/overwrite `mode` to `"opt-out"` and `set_at` to current ISO8601 UTC.
- Preserve every other existing key as-is. Do NOT add `profile`, `preset`, or any other key not already present.
- Pretty-print with 2-space indent and trailing newline.

## API / interface design

### New Step 5 in `01-activation-preflight.md` (first-activation notice)

Inserted between current Step 4 (activation decision) and the existing no-op step (which becomes Step 6). Trigger: activation decision resolved to active (any of the proceed branches in Step 4).

**Notice text (verbatim, single line):**

```
agentic-engineering: active (mode=<mode>, marker=<marker or 'none'>, profile=<profile>, preset=<preset or 'none'>). Run /agentic-status to inspect, /agentic-disable to opt out.
```

Values come from the resolver outputs of Steps 1-3. The literal JSON `null` for preset is rendered as the string `none` at print time (M1).

**Sentinel write contract (race-safe):**
1. Compute path: `<project_root>/.agentic/.activated`.
2. Ensure `.agentic/` exists (`mkdir -p`); failures silently swallowed.
3. Attempt **create-only** write:
   - Python: `open(path, 'x')` (raises `FileExistsError` if present).
   - Shell: write to `<path>.tmp.<pid>`, then `ln <tmp> <path>` (atomic, fails on EEXIST), unlink tmp.
4. **Print the notice if and only if the create succeeded.** Losers stay silent.
5. Filesystem errors other than EEXIST (read-only FS, permission denied, ENOSPC) are silently swallowed; notice may re-print on next session. Methodology must not crash.

**TTY/QUIET gate:**
- If `os.environ.get("AGENTIC_QUIET") == "1"` OR `not sys.stdout.isatty()`, skip BOTH the print AND the sentinel write.

### `bin/agentic-status` (Python 3 stdlib, executable)

Read-only resolver dump. No filesystem writes. Module manifest header required.

**Output format (plain text, one field per line):**

```
agentic-engineering status
  global config: <path> (<found|missing>)
  mode: <mode>
  profile: <profile> (source: <global|project|preset-resolved>)
  preset: <preset or 'none'> (source: <global|project|none>)
  set_at: <ISO8601 or 'unset'>
  project marker file: <path or 'none'>
  marker: <opt-in|opt-out|none>
  active: <yes|no>
  sentinel: <path> (<present|absent>)

Note: deleting the sentinel re-arms the first-activation notice only.
To opt out, use /agentic-disable.
```

Exit code: 0 always (read-only inspection).

### `bin/agentic-disable` (Python 3 stdlib, executable)

**Default behavior (no flags):** writes opt-out marker to project `AGENTS.md`.

**Flags:**
- `--global`: also writes opt-out to `~/.claude/agentic-engineering.json`.
- `--force`: when an existing `agentic-engineering: opt-in` marker is present, remove that line and then append opt-out. Without `--force`, exit non-zero.

**Behavior contract:**

1. **Opt-in conflict gate (MAJOR 1):**
   - Resolve project `AGENTS.md` (follow `CLAUDE.md` `@AGENTS.md` import per Step 2 of preflight).
   - If AGENTS.md exists, scan for whole-line `agentic-engineering: opt-in` (case-insensitive, optional leading whitespace and `- ` prefix).
   - If `opt-in` is present AND `--force` is NOT set: **exit non-zero (exit 2)** with message:
     ```
     agentic-engineering: cannot opt out - existing 'opt-in' marker at <abs_path>:<line> takes precedence. Remove that line first, or use --force to remove it for you.
     ```
     Do NOT append opt-out. Do NOT modify any file.
   - If `opt-in` is present AND `--force` IS set: remove the entire `opt-in` line (including its trailing newline), then proceed to step 2 (idempotency check) and step 3 (append). Note in confirmation output: `--force: removed existing 'opt-in' marker at line <N>.`

2. **Marker idempotency check:**
   - If AGENTS.md does not exist: create one at `<project_root>/AGENTS.md` with a single line: `agentic-engineering: opt-out\n`. Print: `Created <abs_path> with opt-out marker (N bytes).` Rationale (M3): the user invoked `/agentic-disable`, an explicit opt-out signal; creating `AGENTS.md` with the marker is the minimum-blast-radius way to record that intent.
   - If AGENTS.md exists, scan for whole-line `agentic-engineering: opt-out` (case-insensitive, optional leading whitespace and `- ` prefix).
   - If found: no-op. Print: `agentic-engineering: already opted out at <abs_path>:<line_number>. No changes.` Exit 0.

3. **Append insertion point:**
   - Read AGENTS.md as bytes.
   - If file ends with `\n\n` or is empty: append `agentic-engineering: opt-out\n`.
   - If file ends with `\n` but not `\n\n`: append `\nagentic-engineering: opt-out\n`.
   - If file does not end with `\n`: append `\n\nagentic-engineering: opt-out\n`.
   - Write atomically (tmp+rename).

4. **Confirmation output:**
   ```
   /agentic-disable: wrote opt-out marker.
     path: <abs_path>
     bytes written: <N>
     line: <line_number_of_new_marker>
   ```
   With `--force`, prepend the `--force: removed existing 'opt-in' marker at line <N>.` line.

5. **`--global` JSON round-trip rule:**
   - Read `~/.claude/agentic-engineering.json` as JSON. If missing, create with minimal shape: `{"mode": "opt-out", "set_at": "<iso8601_utc>"}`.
   - If present: parse, set `mode = "opt-out"`, set `set_at = "<iso8601_utc>"`.
   - **Preserve EXISTING fields only.** Verbatim rule: "the helper writes back the same set of keys it read; absent keys remain absent."
   - Write back atomically (tmp+rename), 2-space indent, trailing newline.
   - Print: `/agentic-disable --global: updated ~/.claude/agentic-engineering.json (mode=opt-out, set_at=<iso>). Preserved keys: [<list>].`

6. **Destructive-action gate:** `/agentic-disable` is reversible (the marker is one line; the JSON edit is round-trippable). No extra confirmation prompt. `--force` is also reversible (removed `opt-in` line is recoverable from git). Direct-action eligible.

### `content/commands/agentic-status.md` and `content/commands/agentic-disable.md`

User-facing markdown command specs. Each documents usage, flags, exit codes, and references the corresponding `bin/` implementation. **No module manifest required** (matches `agentic-cost.md` precedent).

## Implementation steps

All `content/**` edits route through `/update-agentic-engineering`. Build outputs (`.claude/commands/...`, `.codex/commands/...`, `.cursor/commands/...`) regenerate via `.claude/build.sh` and siblings. The METHODOLOGY.md mirror is auto-built from `content/sections/*.md` by `scripts/build-methodology.sh`.

1. **Edit `content/sections/01-activation-preflight.md`:** Insert new Step 5 (first-activation notice) between current Step 4 and the existing no-op step (which becomes Step 6). Step 5 prose includes the TTY/QUIET gate, race-safe sentinel write contract, EEXIST-silent-skip rule, error-swallow rule, and the verbatim notice text with `<preset or 'none'>` rendering. Inline comment documents the race-safe pattern.

2. **Edit `content/sections/01-activation-preflight.md`:** Renumber existing Step 5 to Step 6. Update internal cross-references in the same file.

3. **Verify Step 5/6 references in other content files (M1):** Plan-time grep already verified that no other `content/**` file references the preflight Step 5. The Step 5 hits in `content/commands/{skeptic.md,implement-ticket.md,test-suite-comprehension.md,cleanup-worktrees.md,wrap.md}` and `content/references/skeptic-protocol.md` refer to those files' own internal step numberings and need no update. Document this verification in the PR description.

4. **Create `bin/agentic-status`** (Python 3 stdlib, executable, `chmod 755`). Module manifest header required. Implements the resolver dump per the API spec above. Reads `~/.claude/agentic-engineering.json`, project AGENTS.md (resolving through `CLAUDE.md` `@AGENTS.md` import), and `.agentic/.activated` sentinel. Writes nothing. Exit 0.

5. **Create `bin/agentic-disable`** (Python 3 stdlib, executable, `chmod 755`). Module manifest header required. Implements the behavior contract above: opt-in conflict gate, `--force` handling, idempotency, append insertion, `--global` JSON round-trip. Atomic writes via tmp+rename. Exit codes: 0 on success/no-op, 2 on opt-in conflict without `--force`.

6. **Create `content/commands/agentic-status.md`** (markdown user-facing spec). Documents usage and references `bin/agentic-status`. Output format verbatim. Includes sentinel-as-reset note. **No manifest header** (matches `agentic-cost.md`).

7. **Create `content/commands/agentic-disable.md`** (markdown user-facing spec). Documents flags (`--global`, `--force`), exit codes, opt-in conflict behavior. Includes the auto-create AGENTS.md rationale. **No manifest header**.

8. **Build pipeline (M2):** No hand-maintenance step. `.claude/build.sh` regenerates `.claude/commands/agentic-status.md` and `.claude/commands/agentic-disable.md` automatically; `scripts/build-methodology.sh` reassembles METHODOLOGY.md from sections. Run `.claude/build.sh`, `.codex/build.sh`, `.cursor/build.sh` once to regenerate artifacts.

9. **Eval harness handling:** no harness change required. The TTY/QUIET gate suppresses sentinel writes in piped-stdout contexts. Document the suppression mechanism in `evals/LEARNINGS.md` so future eval contributors understand it.

10. **Docs sync (PR #28):** update `docs/agentic-engineering.html` to reflect new Step 5 in the preflight section and add `/agentic-status` and `/agentic-disable` to the commands list. Update relevant `docs/slides/*.md` and rebuild Marp output. Same PR.

11. **Manual verification:** run `agentic-status` on this repo; run `agentic-disable` on a scratch worktree (no opt-in); run `agentic-disable` on a scratch worktree WITH opt-in present (verify exit 2 + correct error); run `agentic-disable --force` on the same (verify opt-in removed and opt-out appended); confirm sentinel race-safety with two concurrent shells racing first activation in a fresh fixture.

**Manifest notes:**
- `[bin/agentic-status]` - new non-trivial Python module, manifest header **required** (per code-standards.md and `bin/agentic-cost` precedent).
- `[bin/agentic-disable]` - new non-trivial Python module, manifest header **required**.
- `[content/commands/agentic-status.md]` - markdown user-facing spec, **no manifest** (matches `agentic-cost.md`).
- `[content/commands/agentic-disable.md]` - markdown user-facing spec, **no manifest**.

## Trade-offs and constraints

**Alternatives considered:**

- **(chosen) Refuse on opt-in conflict + `--force` flag.** Cleanest separation: removing user-authored lines is destructive, gate it behind explicit `--force`. The default never produces inert markers.
- **(rejected) Insert opt-out at top-of-file (before any opt-in)** so it wins per Step 3 first-marker precedence. Rejected: contradicts the "append at EOF" idempotency rule, inserts content above user-authored material, higher blast radius.
- **(rejected) Always append opt-out at EOF and warn.** This was iteration 2's approach. Rejected in iteration 3: produces an inert marker the user is misled to believe is active.
- **(chosen) Python scripts in `bin/` per `agentic-cost` precedent.** Consistent with the only existing precedent in this repo. Stdlib-only keeps install footprint zero.
- **(rejected) Inline shell in markdown spec.** Rejected: race-safe `open(path, 'x')`, JSON atomic round-trip, and TTY/QUIET gate need a real execution surface; shell-in-markdown is fragile and harder to test.
- **(rejected) Instruction-driven (agent reads spec and executes via Read/Write/Bash).** Rejected: non-deterministic; race-safety and atomicity become best-effort; eval harness cannot test the helper directly.
- **(chosen) TTY + `AGENTIC_QUIET=1` gate suppresses notice AND sentinel write in non-interactive contexts.** Cleaner separation; no fixture-reset coupling.
- **(rejected) Always print and write, require eval fixture-reset.** Couples eval correctness to methodology side-effect.
- **(rejected) Global sentinel at `~/.claude/.agentic-activated-projects`.** Per-project sentinel composes better with worktree workflows.

**Known limitations:**
- The notice may re-print after sentinel deletion - by design.
- On read-only filesystems the notice prints every session. Acceptable.
- The race-safe pattern requires POSIX `O_EXCL` / `link()` semantics. On exotic filesystems atomicity is best-effort.
- `/agentic-disable` without `--force` will refuse on opt-in conflict. The user is told exactly what to do (`--force` or remove the line manually). This is an explicit safety choice over silent inert writes.
- `/agentic-disable --force` removes the entire `opt-in` line including any leading whitespace and `- ` list prefix. If the line has trailing comments on the same line they are also removed. Recoverable via git.

## Open Questions

None.

## Anti-collision check (vs Gap 2)

Gap 2 also edits `docs/agentic-engineering.html`. Both gaps touch the docs site in the same PR-class but in different sections. Standard mechanical merge - no semantic conflict.

**Action:** if Gap 2 lands first, Gap 3 rebases its docs HTML edits. If Gap 3 lands first, no action required. The `content/sections/01-activation-preflight.md`, new `bin/agentic-{status,disable}` scripts, and new `content/commands/agentic-{status,disable}.md` files are Gap-3-exclusive.

## Acceptance criteria

**Per-file:**

1. `content/sections/01-activation-preflight.md` contains a new Step 5 with: TTY/QUIET gate, race-safe sentinel write contract (create-only, print-gated-on-success), error-swallow rule, verbatim notice text using `<preset or 'none'>`. Existing step renumbered to Step 6.
2. METHODOLOGY.md mirror auto-rebuilt by `scripts/build-methodology.sh` reflects the new Step 5 (verified by inspecting `.claude/skills/agentic-engineering/METHODOLOGY.md` after running `.claude/build.sh`).
3. `bin/agentic-status` exists, executable (`chmod 755`), Python 3 stdlib, manifest header present, implements resolver dump per spec.
4. `bin/agentic-disable` exists, executable, Python 3 stdlib, manifest header present, implements behavior contract per spec including `--force` and opt-in conflict gate.
5. `content/commands/agentic-status.md` exists, no manifest header (matches `agentic-cost.md`), references `bin/agentic-status`, includes sentinel-as-reset note.
6. `content/commands/agentic-disable.md` exists, no manifest header, references `bin/agentic-disable`, documents `--global` and `--force` flags, exit codes, opt-in conflict behavior.
7. `.agentic/` directory entry in gitignore template covers `.agentic/.activated`.
8. `docs/agentic-engineering.html` and `docs/slides/*.md` updated; Marp rebuild committed in same PR.
9. `evals/LEARNINGS.md` notes the TTY/QUIET suppression mechanism.

**Behavioral:**

10. Fresh activation in a TTY with `AGENTIC_QUIET` unset: notice prints exactly once; sentinel created; subsequent sessions in the same project do not re-print.
11. Fresh activation in non-TTY (piped stdout) OR `AGENTIC_QUIET=1`: no notice; no sentinel write; activation proceeds normally.
12. Two parallel subagent activations on a fresh project: exactly one prints the notice; exactly one sentinel created; loser stays silent and does not crash.
13. Read-only filesystem: activation proceeds, notice prints (TTY case), sentinel write silently fails, no crash.
13a. **`/agentic-disable` on a project with `agentic-engineering: opt-in` present and no `--force`:** exits non-zero (exit 2); error message names the absolute path and line number of the opt-in marker; AGENTS.md is unchanged; no opt-out line written.
13b. **`/agentic-disable --force` on a project with `agentic-engineering: opt-in` present:** removes the opt-in line (entire line including newline); appends opt-out per insertion-point rule; confirmation output includes both the `--force` removal note and the standard write summary.
14. `/agentic-status` on an active project: prints all resolver fields including sentinel presence; writes nothing; exit 0.
15. `/agentic-disable` on a project with no existing markers and no AGENTS.md: creates AGENTS.md with single opt-out line; confirmation prints exact bytes + abs path.
16. `/agentic-disable` on a project that already has opt-out marker: no-op; prints "already opted out at <path>:<line>"; exit 0.
17. `/agentic-disable --global` on a config file containing only `mode` and `set_at`: writes back only `mode` and `set_at`; does NOT introduce `profile` or `preset` keys.
18. `/agentic-disable --global` on a config file containing `mode`, `set_at`, `profile`, `preset`: writes back all four keys with `mode` and `set_at` updated; `profile` and `preset` preserved verbatim.
19. **Eval harness fixture run (M5 reworded):** when eval invocations run with stdout piped (non-TTY), the TTY gate suppresses sentinel writes into fixture cwds. Plan-time guarantee: the suppression mechanism is in place and documented in `evals/LEARNINGS.md`. Verification that every eval invocation actually pipes stdout is the eval harness contributor's responsibility and is checked by the eval harness's own integration test (out of scope for this plan).
