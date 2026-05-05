## Operator-confirmed Open Questions

- **Q-ROUTING** and **Q-NOISE**: RESOLVED via Brief amendment #1 (already in Brief). content/** routing only; docs/planning/** and evals/** follow normal feature-branch workflow.

---

Confirmed: 20 components, mean stdev 0.186, max 0.346 - 5% band absurd. Now writing revised plan.

## Technical Plan: evals-baseline-capture (revised, round 2)

### Approach
Build a self-contained Python tool at `evals/baseline/` that captures a point-in-time snapshot of `evals/auto/` and `evals/components/` scores, plus full reproducibility metadata, and writes it atomically to `evals/baselines/2026-05-pre-icl-restructure.json`. The capture is resumable across sessions but refuses to run across SHA changes; the resulting baseline is explicitly framed as one sample from a stochastic distribution, not a regression-equality target.

### Codebase context
- `evals/components/` contains exactly **20 `*.yaml`** files (verified by `ls`); the Skeptic finding's "21" appears to be a miscount, but the fix is the same regardless: enumerate dynamically at validation time, not via a hardcoded constant.
- `evals/results/skeptic.tsv` real data: across n=15 fixtures with stdev>0, mean per-fixture stdev is **0.186** on a [0,1] primary score, max **0.346**, median **0.173**. A 5% absolute band would mark the typical fixture as a regression even when re-running the *same* code at the *same* SHA. This is a Brief P1 issue and is escalated via Open Questions.
- `~/.claude/agentic-engineering.json` exists and influences activation/profile/preset (mode/profile/set_at fields confirmed). This file's contents materially change methodology behavior at the same git SHA - reproducibility metadata must capture it.
- `/update-agentic-engineering` scope (per `content/commands/update-agentic-engineering.md` and METHODOLOGY.md §Delegation): `content/**`, `.codex/skill/**`, three `build.sh` scripts, `hooks/**`, `.codex/hooks/**`. **`evals/**` is NOT in scope.** This unit writes only `evals/baselines/` and reads `evals/components/`, `evals/results/`, `evals/auto/` - normal feature-branch + PR workflow applies.
- Existing eval harness uses Python 3.11 + stdlib + pyyaml (per `agentic-engineering/CLAUDE.md`); follow that convention.
- Module manifest rules (per `content/rules/module-manifest.md`): files exporting public symbols, >50 LOC, or implementing side-effecting operations (file I/O, subprocess) **require** the manifest with all 6 fields. Both new modules in this unit qualify and the manifest is **required**, not recommended.

### Data model

Output: `evals/baselines/2026-05-pre-icl-restructure.json` (single JSON file, atomic write via tmp+rename).

Schema (`schema_version: 1`):

```json
{
  "schema_version": 1,
  "baseline_id": "2026-05-pre-icl-restructure",
  "captured_at_utc": "2026-05-04T...Z",
  "captured_by": "evals-baseline-capture@v1",
  "stochasticity_disclaimer": "This baseline is one sample of a stochastic distribution. Stage 6 comparison MUST be distributional (e.g. Wilcoxon signed-rank against recorded n=3 medians or per-fixture-stdev-multiplied bands), NOT point-equality or fixed-percent thresholds.",
  "git": {
    "ai_tools_sha": "<HEAD of repo root>",
    "ai_tools_dirty": false,
    "agentic_engineering_sha": "<submodule HEAD>",
    "agentic_engineering_dirty": false,
    "helios_sha": "<submodule HEAD or null>",
    "helios_dirty": false
  },
  "environment": {
    "claude_cli_version": "<output of `claude --version`>",
    "claude_config_snapshot": "<verbatim stdout of `claude config list` or equivalent; null if command unavailable, with reason recorded>",
    "agentic_engineering_json": { "<verbatim contents of ~/.claude/agentic-engineering.json>": "..." },
    "agentic_engineering_json_path": "/Users/.../.claude/agentic-engineering.json",
    "model_tier_default": "<resolved model name>" | "unknown:<reason>",
    "python_version": "3.11.x",
    "platform": "darwin-arm64",
    "hostname": "<machine hostname>"
  },
  "components": [
    {
      "name": "skeptic",
      "manifest_path": "evals/components/skeptic.yaml",
      "manifest_sha256": "<hash of yaml file>",
      "fixtures": [
        {
          "fixture_hash": "8c81a569...",
          "fixture_description": "Worker adds an 80-LOC module...",
          "primary_score_median": 0.0,
          "primary_score_stdev": 0.0,
          "n_runs": 3,
          "status": "ok",
          "captured_at_sha": "<ai_tools SHA at moment this fixture was captured>"
        }
      ]
    }
  ],
  "components_skipped": [
    { "name": "...", "reason": "no rows in results tsv" }
  ],
  "components_failed": [
    { "name": "...", "reason": "<error>" }
  ],
  "manifest_enumeration": {
    "discovered_yaml_files": ["evals/components/adr-drift-detector.yaml", "..."],
    "count": 20,
    "all_accounted_for": true
  }
}
```

Every component-yaml in `evals/components/*.yaml` MUST appear in exactly one of `components`, `components_skipped`, or `components_failed`. The validator enforces this at write time.

### API / interface design

Two new modules under `evals/baseline/` (new directory, separate from `evals/auto/` and `evals/components/`):

**`evals/baseline/capture.py`** (CLI entrypoint; required manifest header, all 6 fields):

```python
# CLI:
#   python -m evals.baseline.capture --output evals/baselines/2026-05-pre-icl-restructure.json
#   python -m evals.baseline.capture --resume   # continues prior in-progress capture
#
# Public API (importable):
def capture_baseline(output_path: Path, resume: bool = False) -> BaselineResult: ...
def collect_component_scores(component_yaml: Path, results_tsv: Path) -> ComponentEntry: ...
def collect_environment_metadata() -> EnvironmentDict: ...
def collect_git_metadata() -> GitDict: ...
```

**`evals/baseline/validate.py`** (validator; required manifest header, all 6 fields):

```python
# CLI:
#   python -m evals.baseline.validate evals/baselines/2026-05-pre-icl-restructure.json
#
# Public API:
def validate_baseline(path: Path) -> ValidationResult:
    """
    Validation steps (all must pass):
      1. JSON loads, schema_version == 1.
      2. Required fields present (git, environment, components, stochasticity_disclaimer).
      3. git.*_dirty all False.
      4. Dynamically enumerate evals/components/*.yaml; assert every file appears in
         exactly one of components | components_skipped | components_failed. Mismatch
         is a hard fail with the missing/extra names listed.
      5. Every fixture has primary_score_median in [0,1], n_runs >= 1, status in {ok,error,...}.
      6. environment.agentic_engineering_json is a dict (or explicit null with reason).
    Returns ValidationResult(ok: bool, errors: list[str], warnings: list[str]).
    """
```

**Resume protocol (progress sibling file):**

`evals/baselines/2026-05-pre-icl-restructure.json.progress` (gitignored under `.agentic/`-style discipline OR explicitly listed in `.gitignore`):

```json
{
  "schema_version": 1,
  "started_at_sha": "<ai_tools SHA at session 1 start>",
  "started_at_utc": "...",
  "components_completed": [
    { "name": "skeptic", "captured_at_sha": "<must equal started_at_sha>", "entry": { ... } }
  ],
  "components_remaining": ["architect", "..."]
}
```

Resume preconditions (ALL must hold or refuse-and-explain):
1. `evals/baselines/<name>.json.progress` exists and parses.
2. Current `git rev-parse HEAD` (ai_tools) **equals** `started_at_sha`.
3. `git status --porcelain` returns empty (working tree clean) for ai_tools AND every submodule referenced in started state.
4. `~/.claude/agentic-engineering.json` SHA-256 matches the snapshot recorded at session 1.

If any precondition fails: print the specific failure, do NOT continue. Operator's options are restart-from-zero or abandon. Cross-SHA contamination is not silently permitted.

**Atomicity note (corrected):** The final baseline JSON does not exist mid-capture; only `<name>.json.progress` exists during capture. On final-write success, progress is deleted and the baseline is renamed into place via tmp+rename. There is no window in which a partial baseline JSON could be misread as complete.

### Implementation steps

1. Create directory `evals/baseline/` (new module).
2. Write `evals/baseline/__init__.py` (empty or version constant).
3. Write `evals/baseline/capture.py` with the manifest header (all 6 fields populated: Purpose, Public API, Upstream dependencies, Downstream consumers - including `evals/baseline/validate.py` and the future Stage 6 comparison runner -, Failure modes, Performance). Implement: argparse CLI; git/environment/`~/.claude/agentic-engineering.json` collection; per-component score extraction from `evals/results/*.tsv`; progress-file writes after each component; final tmp+rename; resume preconditions.
   - `evals/baseline/capture.py` - new non-trivial module, manifest header **required** (per `content/rules/module-manifest.md`). Module qualifies (>50 LOC, side-effecting file I/O + subprocess, public API).
4. Write `evals/baseline/validate.py` with the manifest header (all 6 fields). Implement validator steps 1-6 above. Step 4 (dynamic enumeration) is the key safeguard against silent component drop.
   - `evals/baseline/validate.py` - new non-trivial module, manifest header **required**.
5. Add `.gitignore` entry: `evals/baselines/*.progress`. The completed baseline JSON IS committed; the progress sibling is not.
6. Add a smoke test or scenario under `evals/auto/` that invokes `validate_baseline()` against a fixture baseline and asserts ok==True. (Stage 6 will reuse this.)
7. Run capture once on the operator's machine; commit the resulting `evals/baselines/2026-05-pre-icl-restructure.json` and the new code in a single PR against `develop` (or the resolved BASE_BRANCH). **Routing:** standard feature-branch + PR. Not via `/update-agentic-engineering` - that command's scope does not include `evals/**`.

**Per-consumer impact table:** Not applicable. This unit creates new files under `evals/baseline/` (new module) and writes new files under `evals/baselines/`. No existing shared utility, shared component, or shared type is modified. No file under `packages/<shared>/`, `lib/shared/`, or `src/shared/` is touched. Trigger does not fire.

Known-future consumer of the baseline JSON contract: the Stage 6 comparison runner (Brief P2). `schema_version: 1` is the binding contract. If Stage 6 needs additional fields, it bumps to `schema_version: 2` and the validator gains a v2 branch; v1 baselines remain readable.

### QA criteria

```yaml
qa_criteria:
  qa_skip: pure-backend-library
  qa_skip_rationale: "CLI tool that produces a JSON artifact; no UI, no service surface, no user-facing runtime path. Verification is the validator output (exit code + structured errors) plus the committed JSON file's schema conformance."
  scenarios: []
  manual_smoke: "none"
```

Rationale check: capture.py is a one-shot CLI, validate.py is an offline JSON checker, neither exposes an HTTP/UI/service surface. The "runtime" path that matters is the validator's exit code, which is exercised by the smoke scenario in step 6 and by the validator's CLI return code itself.

### Trade-offs and constraints

**Alternatives considered:**
- Reuse `evals/auto/` framework as the capture tool: rejected - `evals/auto/` runs scenarios; baseline capture extracts already-computed `evals/results/*.tsv` data. Different concern; a thin extractor is simpler than retrofitting auto.
- Single-file script (no `evals/baseline/` package): rejected - the validator is a separate concern with its own CLI and its own consumers (Stage 6 will import `validate_baseline`); a package boundary is correct.
- Skip the `claude_config_snapshot` field because the command may not exist on all machines: rejected - explicit-null-with-reason is honest; silent omission would let the field appear "captured" when it wasn't. Validator step 6 enforces explicit null.
- Pin via container/lockfile rather than metadata snapshot: rejected as out of scope for this unit; the snapshot approach is what the Brief asks for. Containerization is a future hardening step, not a blocker here.

**Known limitations:**
- `claude config list` (or equivalent introspection) may not exist; we record explicit null with the reason and accept this gap. Operator should be aware that model routing is not perfectly captured.
- Prompt-cache state cannot be captured (Anthropic-side state). Documented in `stochasticity_disclaimer`.
- The baseline is one sample. The 0.186 mean stdev observed in `skeptic.tsv` means the regression test at Stage 6 cannot use a fixed-percent band; this is surfaced as Open Question Q-NOISE below.

### Open questions

**Q-ROUTING (operator decision required - contradicts Brief constraint).** The Brief Constraints section states "All changes routed through /update-agentic-engineering (content/** is methodology source-of-truth)." This unit writes `evals/baseline/*.py`, `evals/baselines/*.json`, and a `.gitignore` entry - none of which fall within `/update-agentic-engineering`'s documented scope (`content/**`, `.codex/skill/**`, `build.sh` scripts, `hooks/**`, `.codex/hooks/**`). The Brief constraint is over-broad as written. Recommended resolution: amend the Brief to scope the routing constraint to `content/**` work specifically; route `evals/**` work through normal feature-branch + PR into `develop`. Operator must confirm before engineer spawn.

**Q-NOISE (operator decision required - Brief P1 success criterion change).** Brief P1 says "no per-component score regression beyond a 5% noise band." Empirical data from `evals/results/skeptic.tsv`: across n=15 fixtures with stdev>0, mean per-fixture stdev is **0.186** on a [0,1] scale, max **0.346**, median **0.173**. A 5% absolute band would mark essentially every fixture as a regression on a same-SHA re-run. Two viable resolutions:
  - **(a)** Replace the absolute band with a per-fixture multiple of recorded stdev (e.g., flag regression only when `new_median < old_median - k * old_stdev`, k=2 default).
  - **(b)** Replace point comparison with a non-parametric distributional test (Wilcoxon signed-rank or Mann-Whitney) against the recorded n=3 medians, with alpha=0.05.
  
  This is a Brief-level success-criterion change and must not be silently picked. Both options are defensible; (b) is statistically cleaner but assumes Stage 6 captures n>=3 runs per fixture (matches current `evals/auto/` convention). Recommended default if operator has no preference: (b) with alpha=0.05. Operator must confirm before engineer spawn.

**Q-COMPONENT-COUNT (informational, not blocking).** Skeptic finding cited "21 components"; actual `evals/components/*.yaml` count is **20** (verified by `ls`). This unit's validator step 4 enumerates dynamically and is robust to either count - the structural fix in the validator is the same regardless of whether 20 or 21 is "correct." No operator decision required; flagged for transparency.

Per METHODOLOGY.md §Delegation, the Open Questions hard gate applies: Q-ROUTING and Q-NOISE both require operator resolution before any engineer spawn on this unit.