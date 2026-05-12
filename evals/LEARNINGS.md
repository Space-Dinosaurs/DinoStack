# Evals learnings

Accumulated lessons from building component evals. Read this before starting a new component eval - each lesson below was paid for in rework.

## Invocation path matters and is easy to get wrong

The eval must invoke the component via the SAME path humans use in production. For named agents, that means the Task-tool subagent-spawn path, NOT a top-level `claude -p` session pretending to be the named agent.

- **Symptom if wrong:** a top-level session told to "follow content/agents/foo.md" does not get the frontmatter applied (tools, model, description). What you measure is a plain Claude session plus a Read, not the named agent.
- **Correct pattern:** two-level spawn. Outer `claude -p` session is a thin spawner with `Task` in allowed-tools. Its prompt: "Use Task with subagent_type='<agent_name>' and prompt=<brief>. Return the subagent's response verbatim." The normalizer extracts the subagent's output from the outer Task result, filtering nested tool_results by `parent_tool_use_id`.
- **When the invocation path must be a proxy:** if the component is session-level (like the main conductor's in-flight routing), the eval can only measure a proxy (the `orchestration-planner` named subagent in Phase 3's case). Document this limitation upfront in the component README's "what this measures vs. doesn't" section. Do not oversell.

## Scoring-function floors and ceilings kill signal

A scoring function that floors at 0 or ceilings at 1 on most fixtures cannot detect prompt variants. Phase 1's v1 Skeptic scorer floored sk-001 and sk-002 at 0.0 because FP-Major penalty was absolute (-0.1 each) while `max_achievable` was tiny (0.5 for single-Major fixtures). A Skeptic catching the TP plus 5 FPs computed to -1.2 → clipped to 0, and no prompt improvement could surface.

- **Rule:** a Skeptic-correct component that catches the TP MUST be able to score above 0 regardless of false-positive noise. Cap FP penalty at ~50% of max_credit (or `max(max_credit, 1.0) * 0.5`). This was Phase 2's v2 fix.
- **Rule:** clean-control fixtures (no expected findings) need their own scoring path that doesn't divide by zero.
- **Test before trusting:** the sensitivity-check pattern. Run the eval twice on the same prompt to observe within-prompt noise. Then edit the prompt (a plausible, small calibration change) and run again. If fewer than ~60% of fixtures move outside their noise envelope, either the scorer saturates or the fixtures don't exercise the sensitive region.

## Vocabulary enforcement belongs in the prompt, not the fixture

If the scorer does exact-string matching on an enum (decision_class, severity, category), the prompt MUST enumerate the valid values. Phase 3 burned a round because the enum values were invented by the fixture author, never referenced in `content/`, and never shown to the planner. The planner emitted natural synonyms ("tight_fix" vs "tight_fix_path") and scored 0 for vocabulary, not routing.

- **Rule:** in the prompt, list the exact enum strings the scorer expects. This is scaffolding, not telegraphing - the planner still has to choose which option applies.
- **Do not** add "synonym maps" to the scorer as a workaround. Enforce vocabulary at the prompt layer; keep scoring exact.

## Telegraphing is the most insidious fixture defect

A fixture's observed_state or context MUST describe situational FACTS (what happened, what state exists, what artifacts the subagent can see). It must NOT describe the rule that governs the correct answer. If the planner can pick the right answer by restating quoted text in the prompt, the eval measures restatement, not reasoning.

- **Bad:** `other_context: "The persistence loop contract says iteration 3 is the cap."` - tells the planner the rule.
- **Good:** `other_context: "Three engineer fix passes have run on this ticket. The most recent Skeptic review raised the same Major finding again."` - tells the planner the state; the planner must retrieve the rule from its loaded `content/` files.
- **Test per fixture:** could a human labeler reading ONLY the fixture (not the methodology files) guess the expected decision? If yes, the fixture is telegraphing.
- **Process rule:** the fixture author should draft the fixture, ask an independent reader (or a cold agent) to solve it without access to the methodology files, and revise until the cold reader cannot determine the answer.

## Isolation claims must match isolation mechanisms

Phase 1 initially declared Tier 1 as "worktree-only" but granted `Bash` tool access and `acceptEdits` permission. That's not read-only isolation - it's a shell + write session with a git worktree. The fix was to drop Bash and edit tools; Tier 1 now means Read, Grep, Glob, Task only, with `default` permission mode.

- **Rule:** the isolator's allowed_tools list must match its declared tier. Tier 1 = read-only review, no Bash, no Write, no Edit. Tier 3 = full execution in Docker with network denied by default.
- **Network:** Tier 1 currently does NOT enforce network denial (relies on tool list being read-only). If a future read-only component needs Bash or network, it is NOT Tier 1 - upgrade it to Tier 2 or 3 and implement the isolation.
- **Do not** use "git worktree per run" as a synonym for isolation. It isolates the working tree; it does not isolate network, HOME, or nested subagent grants.

## Fixture hash should hash meaning, not bytes

Phase 1 initially hashed fixture YAML bytes directly for `fixture_hash`. That meant a cosmetic description tweak (even a single character) changed the hash - particularly sensitive if a local pre-commit secret-scanner false-positive-matched certain SHA substrings and forced a reword. The fix: hash only the semantic fields (`id`, `inputs`, `expected_findings`, `expected_signoff_granted`) via canonical JSON.

- **Rule:** `fixture_hash = sha256(json.dumps(semantic_subset, sort_keys=True, separators=(",", ":")))`. Descriptions, comments, and `protocol_sha` are not in the subset.
- **Benefit:** hash is stable across local-hook churn and reword polishing. Only a meaningful fixture change invalidates the row.

## Prompt-neutral edits vs. behavioral edits

When you need to rotate a fixture hash (e.g. to dodge a secret-scanner false-positive), the edit must be SEMANTICALLY NEUTRAL. Adding instruction text like "Return exactly one decision." changes the component's output-shape pressure on that fixture relative to its peers. The correct rotation mechanisms are:
- Toggle a trailing blank line inside a free-text YAML block
- Change YAML block-scalar style (`|` to `|+`) - preserves rendered content
- Reorder unused YAML keys alphabetically

If you can't dodge the false-positive with a neutral change, the correct fix is to the scanner rule, not the fixture.

## Run the sensitivity check before declaring a phase done

A component eval is "done" when it can distinguish two plausible variants of the component's source text, not when it produces a TSV. Phase 3 first ran with all fixtures pinned at floor/ceiling; the eval produced numbers but was measuring vocabulary, not routing. The sensitivity check - run baseline twice, then a plausible variant, then compare - is how you verify the signal path before investing in more fixtures.

- **Rule:** before expanding a component's fixture corpus past the initial 5-10, run a sensitivity check. If <60% of fixtures move on a plausible prompt edit, fix the scorer or re-author fixtures before scaling.

## Overfitting Rule in practice

`evals/OVERFITTING-RULE.md` says: edits to `content/` motivated by a TSV score must satisfy "if this exact fixture disappeared, would this edit still be a worthwhile change?" The rule is easy to state and hard to apply - the temptation to chase a low score is real.

- **Concrete pattern that passes the rule:** a scorer-side change (tightening precision/recall calibration) motivated by multiple fixtures showing the same shape of defect.
- **Concrete pattern that fails the rule:** editing `orchestration-planner.md` to canonicalize `decision_class` vocabulary because co-008 scored 0.286. That's chasing a single fixture's vocabulary quirk. The better fix is either fixture rewording or accepting the low score.
- **Document non-fixes too:** when a low-scoring fixture is a known limitation that we deliberately chose not to fix, note it (in the fixture README, in the commit message, or in this doc). Silent acceptance is how overfitting sneaks in later.

## Content glob is load-bearing

The `content_glob` in the component manifest determines which files' changes invalidate the content-hash cache. If a file contains rules the component's correctness depends on but is not in the glob, a change to that file silently leaves the content_hash the same and the eval produces stale results.

- **Rule:** glob includes every file the component's correct behavior couples to. For the conductor eval, that means `orchestration-planner.md`, `agent-methodology.md`, AND `implement-ticket.md` (which owns Phase 6/6b cap rules). Phase 3 initially missed `implement-ticket.md`.
- **Do not** include files just because they're nearby. Ad-hoc inclusion over-invalidates the cache on unrelated edits and makes TSV rows look less comparable than they are.

## stdev of zero is data, not noise

A fixture that produces stdev=0.000 across N=3 runs is saying: the component's output is deterministic on this scenario at this sample size. That's not a bug unless it happens on EVERY fixture - then the eval lacks dynamic range.

- **Rule:** the planning doc's ordering criterion `|median_A - median_B| < stdev` is undefined when stdev=0. Either supplement with cross-fixture median spread (the practical alternative we adopted in Phase 3), or increase N to induce visible variance for statistical tie-breaking.
- **Practical target:** at least 2 fixtures with non-zero stdev in any component's baseline run, as a sanity check that the eval is exercising uncertainty somewhere.

## Things still unresolved across the whole eval system

- **Per-fixture cost caps.** The runner doesn't enforce a per-fixture token budget. A runaway subagent burns tokens silently.
- **protocol_sha drift warning.** Implemented but no enforcement. A drifted fixture still runs and scores; the warning just logs.
- **No cross-component regression harness.** A change to one component's prompt that indirectly affects another (e.g. a shared subagent) is invisible until someone manually re-runs the other component's eval.
- **Fixture labeling is human-heavy.** No proposal for scaling beyond the current hand-authoring pace.
- **Scorer versioning.** `scorer_version` is recorded but the runner does not warn when a newer scorer rolls in and invalidates prior rows.

## Slash commands are not discoverable under redirected HOME

Tier 2 evals redirect `$HOME` to a tmpdir to contain blast radius. Inside
that fake HOME the skill / command install path is absent, so
`claude -p "/init-project"` returns `Unknown command: /init-project`.
Telling the runner to invoke a slash command in that environment
measures nothing.

- **Rule:** for slash-command evals, inline the verbatim command body
  as the `-p` prompt content. Add a synthetic auto-memory banner, a
  fixture-context preface, and a non-interactivity directive around it.
  Do not invoke `/slash-name`. This is a proxy; document it in the
  component README's invocation-caveat section.

## Tier 2 command-mode runs are "raw-prompt" by design

The `[raw-prompt]` TSV description prefix was designed to flag UNEXPECTED
fallbacks on agent-mode runs where the Task spawn didn't resolve. For
command-mode runs (`invoke.mode == "command"`), there is no Task wrapper
- raw-prompt IS the intended path. Tagging every command-mode row with
`[raw-prompt]` makes every row look like a fallback.

- **Rule:** only prefix `[raw-prompt]` when `invoke_mode == "agent"` and
  some run fell back to raw-prompt. The cli.py conditional
  `if invoke_mode == "agent" and ...` is the right guard; it was landed
  correctly in the Turn 1 cli.py and needs no further change.

## Scorer weights must sum to 1.0 (or the documented ceiling)

init_project_lite v1 weights summed to 0.95, so a flawless scaffold
scored 0.95. Fixture authors reading the TSV see 0.95 and assume one of
the five dimensions was missed. There was no sixth dimension - v1 just
didn't normalize.

- **Rule:** renormalize weights so a perfect run scores 1.0. Add a
  runtime assertion (`assert abs(sum(weights) - 1.0) < 1e-9`) so future
  additions that shift the total surface immediately. This was v2's fix.

## Filesystem snapshot alone is insufficient for line-level scoring

init_project_lite needs to inspect AGENTS.md and .gitignore contents
(not just existence) to check required-section coverage and required
substrings. A pure `sha256` snapshot cannot satisfy that; the scorer
reads the files directly from disk.

- **Rule:** the invoker must keep the worktree alive through the
  scoring phase and stash `worktree_root` on the run record before the
  isolator cleans up. If a scorer needs file-level inspection, it reads
  from `worktree_root` not from the snapshot. Cleanup is the caller's
  responsibility, done AFTER scoring completes.

## "No applicable conditional" is not the same as "zero conditional hits"

init_project_lite v2 still computes `conditional_present /
max(conditional_total, 1)` for every fixture, including fixtures whose
`expected_signals: []` means no conditional files should ever appear.
Those fixtures score 0 / 1 = 0 on the conditional dimension, losing
0.158 of the weighted sum for a dimension that is not applicable. Both
ip-002 (python-poetry, no signals) and ip-005 (greenfield) hit this and
settle at 0.8421 despite doing everything /init-project asked of them.

- **Recognised limitation, not fixed in v2:** raising this to v3 by
  scoring vacuous dimensions 1.0 would saturate all 5 fixtures at 1.0
  and eliminate sensitivity-check headroom. The clean fix is to
  simultaneously (a) make non-applicable dimensions vacuous and (b) add
  fixtures that exercise the remaining headroom (e.g. tracker signal,
  AGENTS.md line-budget stressor). Document this as a known-limitation
  in the fixture README rather than silently letting 0.842 look like
  fixture-level misbehaviour.

## Sensitivity headroom requires at least one slack dimension

Phase 4's full-run baseline produced stdev=0 on all 5 fixtures. That
means every fixture is either at floor or at a stable structural score;
a plausible prompt edit has no dimension to move. The calibration-level
sensitivity edit (AGENTS.md line budget `45 -> 40`) only moves fixtures
where the generated AGENTS.md lines straddle the threshold. Current
runs produce 29-38 lines, well under 40, so the edit doesn't move the
median. Fixture corpus expansion should include at least one
AGENTS.md-line-budget stressor (e.g. a decisions-heavy repo) to give
the line-budget dimension teeth.

## Latent-by-design scorer axes are not defects

Scorer v4 (commit 1a1d081) replaced init_project_lite's binary line-budget
flag with a tiered credit: `under` (n <= max_lines) -> 1.0, `grace`
(max_lines < n <= max_lines + 10) -> 0.5, `over` -> 0.0. Weights are
unchanged from v3 and the sum-to-1.0 assertion still holds. The tiered
shape is defensible on its own merit: a 45-line budget is a soft quality
dimension, and a scaffold 2 lines over is meaningfully different from one
20 lines over.

On the current 8-fixture corpus this axis never activates. ip-006 is the
budget-stressor fixture and produces AGENTS.md lengths of [41, 40, 35]
lines across its n=3 baseline runs - all in tier `under`. The other 7
fixtures produce 25-41 lines across their baselines; none crosses 45.
The axis is live in the scorer but vacuous against today's command
behavior.

This is a property of the command's current generator, not a scorer or
fixture defect. A future regression that bloats AGENTS.md past 45 lines
will activate the axis automatically; a future fixture whose seeded
repo genuinely forces a long Decisions section (e.g. a decisions-heavy
mega-repo archetype) would too. Rule: a scorer axis being
vacuous-in-practice against the current corpus is acceptable IF (a) the
axis shape is defensible independent of corpus coverage and (b) the
limitation is documented so a future maintainer does not think the
corpus has bugs that need chasing.

Anti-pattern: lowering a fixture's `agents_md_max_lines` below the
command's natural output just to force movement on this axis. That
fails the Overfitting Rule - the fixture's threshold would no longer
represent a plausible real-world budget, only a number chosen to make
the scorer move.

## Scoped-subset sensitivity: 60% is per-axis, not whole-corpus

The 60% bar ("at least 60% of fixtures move outside their noise
envelope on a plausible prompt edit") from the Sensitivity-check rule
above applies to the subset of fixtures an edit can plausibly move, not
the whole corpus. A budget-axis probe (e.g. line-budget threshold
change) can only move budget-sensitive fixtures; a tracker-axis probe
can only move tracker-sensitive fixtures. Evaluating either probe
against the full 8-fixture corpus under-reports its discrimination.

Working interpretation for future probe design: identify the axis the
probe targets, enumerate the fixtures that exercise that axis, and
apply the 60% bar to that subset. Document both the subset and the bar
in the probe's commit message so a later reader can audit the claim.

## Phase 4 tracker-axis probe: detection is multi-signal robust

Probe (not committed to `content/`): remove `.linear/` directory from
init-project.md's Tracker detection rule (step 0, tracker signal list),
leaving Linear MCP lookup and ticket-pattern commit regex in place.
Rationale: a maintainer might reasonably argue Linear MCP presence is
the load-bearing signal and a `.linear/` directory alone is weak
evidence. Target fixture: ip-007 (the tracker fixture), whose seeded
repo provides `.linear/config.json` as its primary signal plus README
prose mentioning Linear and commit-message prefixes in the README text.

Run: ip-007 n=3 baseline (un-edited) -> median 1.0. ip-007 n=3 probe
(with `.linear/` removed from the rule) -> median 1.0. Delta: 0.0. The
axis did not move. Inspection of the probe runlog shows the command
still detected Linear (one run cited "Linear (`.linear/config.json` -
workspace: `growthco`)") despite the rule no longer listing the
directory as a signal. This is a valid scientific result, not a failed
probe: the command's tracker detection is robust across multiple
signal sources (directory presence, README prose, ticket-pattern text)
and removing one line of the rule does not suppress it.

Implication for Phase 4 closure: the init-project eval can discriminate
on budget shape (the axis is live but vacuous against today's
generator) and has at least one probe-verified robust detection path.
No probe in this session moved any fixture outside its noise envelope.
A stronger tracker-axis probe would need to weaken multiple signals at
once (e.g. remove `.linear/` AND strip the Linear-MCP clause) to
surface a drop, which crosses the line from "plausible maintainer
edit" into "intentional regression" and is out of scope for
calibration.

Anti-pattern avoided: committing probe-variant TSV rows. The probe's
three ip-007 rows were appended to the TSV during the run and then
reverted (`git checkout 1a1d081 -- evals/results/init-project.tsv`)
so the ledger only reflects production-prompt measurements.

## Phase 4 closure

- Scorer: v4 shipped (1a1d081) with tiered line-budget credit; weights
  unchanged.
- Corpus: 8 fixtures (ip-001..ip-008) seeded and baselined at 1.0
  median across the board.
- Budget axis: vacuous against current command generator (ip-006
  lines [41, 40, 35] all tier `under`); correct shape; documented
  above.
- Tracker axis: probe-verified live but multi-signal robust; ip-007
  stays at 1.0 under a plausible single-signal detection-weakening
  edit (remove `.linear/` from the rule). Detection leans on README
  prose and directory presence together.
- Remaining Phase 4 limitation: no single probe moves >=60% of the
  8-fixture corpus; the scoped-subset interpretation above is the
  working definition of "calibrated enough" and is carried forward
  into any future Phase-5 probe design.

## Phase 5 /wrap eval baseline (n=3 under scorer v2)

Scorer shipped in two steps: v1 (550218a) and v2 (4b2e16a). Both use
six weighted dimensions summing to exactly 1.0: file presence (0.25),
context.md section coverage (0.15), substring fidelity (0.20), tiered
route credit (0.15), forbidden-file absence (0.15), lock-release
hygiene (0.10). v2 widens `_ALWAYS_OK_EXTRAS` to exclude Claude Code
runtime config (`.claude/settings.json`, `.claude/settings.local.json`)
and the init-project preflight migration artifact
(`.claude/tracking.md`), and introduces `_STANDARD_ROUTE_SENTINELS`
(`.agentic/memory.md`, `.claude/findings.md`) excluded from extras
only when `route_expected == "standard"` (where their creation is the
route signal already credited by w_route).

Corpus: 5 fixtures (wr-001..wr-005) covering clean-end-of-feature,
Skeptic finding promotion, in-progress refactor, learnings append
against a 14-entry findings.md, and a zero-substance Q&A session.
Every fixture seeds opt-in marker in both `home_config` and the
repo's AGENTS.md; the prompt builder raises at build time if the
marker is missing.

Baseline n=3 medians under v2 (committed at 173b1d4):

- wr-001 (clean light): 1.0, stdev 0.0 - deterministic at ceiling.
- wr-002 (standard, skeptic finding promotion): 0.925, stdev 0.052 -
  REAL nondeterminism from the standard-path draft-Worker + Skeptic
  loop. Across 3 runs: one hit both findings.md substrings cleanly
  (1.0), one paraphrased past "webhook"/"validat" (0.9), one slipped
  the route to light instead of standard (route_credit 0.5 -> 0.925).
- wr-003 (light, in-progress): 1.0, stdev 0.0 - negative substring
  checks ("completed", "done") absent from Recent Focus across all
  runs.
- wr-004 (standard, learnings append): 1.0, stdev 0.0 - memory.md
  captured `router.ts` and `WebhookError`; findings.md gained the new
  async-error entry.
- wr-005 (zero-substance): 1.0, stdev 0.0 - correctly routed; no
  forbidden files created.

Headroom status: wr-002 is the active discriminator with real variance
from subagent nondeterminism. The extras axis is latent-by-design per
the Phase 4 doctrine: v2 removed the v1 false-positive extras hits
(runtime artifacts), and on the current corpus no real over-capture
triggers the axis.

## Phase 5 probe: substring-fidelity weakening (uncommitted)

Probe edit: remove the sentence "Replace all placeholders with real
content from the data provided." from wrap.md Step 1 draft Worker
brief. Rationale: a maintainer might reasonably argue the surrounding
"write None" instruction already handles the template-text concern.
Target axis: w_substrings. Target subset: {wr-001, wr-002, wr-004}
(fixtures with required substrings). Subset 60% bar: 2 of 3 must move
outside noise envelope.

Probe n=3 medians (not committed):

| Fixture | Baseline med/stdev | Probe med/stdev | Median delta |
|---|---|---|---|
| wr-001 | 1.0 / 0.000 | 1.0 / 0.029 | 0 |
| wr-002 | 0.925 / 0.052 | 0.925 / 0.043 | 0 |
| wr-003 | 1.0 / 0.000 | 1.0 / 0.188 | 0 |
| wr-004 | 1.0 / 0.000 | 1.0 / 0.000 | 0 |
| wr-005 | 1.0 / 0.000 | 1.0 / 0.000 | 0 |

**Subset bar: 0 of 3 moved on median. Probe FAILED the 60% bar.**
This matches the Phase 4 tracker-probe outcome: a single-sentence
removal is below the threshold needed to perturb the draft Worker's
substring preservation at n=3. wr-003's variance spike to 0.188
confirms the probe DID affect behavior (one of three probe runs
deviated) but not enough to cross the median.

Honest interpretation: the eval distinguishes real-world behavior
variation (wr-002's 0.925 baseline reflects genuine Worker/Skeptic
nondeterminism), but a probe-level prompt edit needs larger magnitude
to move medians at n=3. This is not a failure of the eval. It is a
fact about the probe's size relative to the sampling noise plus the
prompt's multi-signal redundancy. Stronger probes (remove ALL
substring-preservation pressure, not one sentence) would likely move
medians but cross from "plausible maintainer edit" into "intentional
regression" and lose their validity as calibration evidence.

The substring axis remains live through wr-002's below-ceiling
baseline: a substring-fidelity regression severe enough to push wr-002
consistently below 0.9 would be detectable. The axis doesn't require
the probe passing to be useful.

## Phase 5 session-transcript proxy caveat

Unlike conductor (named subagent, two-level Task spawn) and
init-project (slash command with no session-input requirement), /wrap
in production reads the live Claude Code session transcript. Evals
have no live session. The wrap prompt builder substitutes a
hand-authored `session-transcript.md` per fixture, loaded into the
prompt under `<SYNTHETIC_SESSION_TRANSCRIPT>` with an instruction to
treat it as the authoritative record for Step 0 compilation.

What this measures: /wrap's ability to compile, route, and persist a
pre-digested narrative into context.md, memory.md, findings.md, and
AGENTS.md with correct structure, fidelity, and forbidden-file
discipline. What this does NOT measure: /wrap's ability to introspect
an actual tool-call stream. A maintainer edit to Step 0's survey
language that changes how /wrap reads a live session may not move any
fixture score because the eval pre-digests the session for the
command. This is the same proxy category as the conductor eval
(LEARNINGS line 11) and should be documented in the component's
README.

## Phase 5 closure

- Scorer: v2 shipped (4b2e16a) with tiered route credit, vacuous-safe
  file/section/substring/forbidden axes, and runtime/route-sentinel
  exclusion from extras. v1 dropped two standard-route fixtures by
  0.15 each on false-positive extras; v2 is the correct shape.
- Corpus: 5 fixtures covering the route space (zero-substance, light,
  standard) plus a negative-substring discriminator and a 14-entry
  findings.md-size stressor.
- Baseline n=3 under v2: wr-002 at 0.925 (stdev 0.052) is the active
  discriminator with real Worker+Skeptic nondeterminism; other four
  fixtures at 1.0/0.0. Committed at 173b1d4.
- Probe: substring-fidelity weakening. 0 of 3 target-subset fixtures
  moved on median. Probe n=3 rows NOT committed to the ledger. Result
  recorded above as calibration evidence; matches Phase 4's
  multi-signal-robustness outcome.
- Lock-release axis: latent-by-design. Never tripped in baseline.
- Extras axis (v2): correctly quiet on the current corpus. Latent for
  regression detection.
- Unresolved: a stronger probe design (remove a load-bearing
  paragraph, not one sentence) would likely move medians but cross
  into intentional-regression territory. The eval ships as-is with
  wr-002 as the working discrimination signal and the substring axis
  proven by wr-002's below-ceiling baseline rather than by a passing
  probe.

## P3 /auto-harness MVP: karpathy loop proof of concept

Shipped `/auto-harness` (commit b8e208d) as a standalone Python CLI
under `evals/auto/`. 11 modules + 4 test modules, 23 tests passing,
2036 LOC. One-component-per-invocation design: editor-agent (Claude
with Read/Grep/Glob only) proposes a diff, `apply.py` validates
against editable/locked globs and max_edit_loc, runner re-scores,
keep/revert on `delta >= max(pooled_stdev, 0.02)`. TSV ledger at
`evals/results/auto-harness.tsv`, lock at `evals/.auto-harness.lock`,
state at `evals/auto/state/<branch>.json`.

**First dry-run proof (2026-04-20, branch auto/skeptic-20260420T044453):**

Preflight passed with 15 Skeptic baseline rows at HEAD 9bc4d40.
Baseline scalar (median-of-fixture-medians): 0.5000 with pooled_stdev
0.1486. Editor-agent proposed this edit to `content/agents/skeptic.md`:

```
+ For each off-brief finding, apply a stricter bar before listing it:
+ would a senior engineer reviewing this diff cold - without the
+ adversarial brief - independently flag it as blocking? If the answer
+ is "maybe" or "only given the brief's framing," downgrade to Minor
+ or remove it.
```

Overfitting verdict: pass. The rationale did not reference any
fixture ID. The proposed edit targets the dominant Skeptic-score
failure mode: false-positive penalties from off-brief over-flagging,
which cap many fixtures at 0.5 under the v2 scorer's FP_cap rule.

Loop exited `dry_run_complete` without applying - this was the
smoke-test path. The same invocation without `--dry-run` would have
applied the diff, run n=3 on all 15 fixtures, computed after-median,
and kept-or-reverted per the delta rule.

**What the proof demonstrates:**
1. The preflight gate actually fires (clean tree + not-main + baseline).
2. The editor-agent receives enough context (baseline TSV, brief, rule,
   editable/locked globs) to propose a defensible edit.
3. The diff validator accepts a well-formed proposal.
4. The Overfitting verdict parser works.
5. The loop terminates cleanly and writes the expected summary.

**What the proof does NOT yet demonstrate:**
- A real keep-or-revert cycle (needs `--max-iterations N` without `--dry-run`).
- The runner shim aggregating an after-score correctly.
- Multi-iteration plateau detection (3 consecutive reverts -> exit).
- Budget exhaustion termination.

A subsequent session should run `python -m evals.auto.cli run skeptic
--max-iterations 5 --time-budget-sec 1800` on a clean working branch
to exercise the full keep-or-revert path. MVP is ready; the karpathy
pattern is wired.

## First-activation notice TTY/QUIET suppression (Gap 3)

The activation preflight in `content/sections/01-activation-preflight.md`
gates its first-activation notice and `.agentic/.activated` sentinel
write on a TTY check: when `os.environ.get("AGENTIC_QUIET") == "1"` OR
`not sys.stdout.isatty()`, BOTH the print and the create-only sentinel
write are skipped. Eval harness invocations that pipe stdout (the
default for any subprocess capturing the agent's output) therefore
never produce a sentinel inside fixture cwds and never contaminate
fixture transcripts with the notice. No harness change is required.
If a future eval runs an agent with stdout attached to a real TTY,
contributors should set `AGENTIC_QUIET=1` explicitly to keep fixture
state clean. Verifying that every harness invocation actually pipes
stdout is the eval harness contributor's responsibility (per the Gap 3
plan; AC #19).

## Skill-comparison eval build (2026-05-12)

### No fabricated data in corpus files

Task corpus files must reference real SHAs from the canonical
`princeton-nlp/SWE-bench_Lite` source. Fabricated commit hashes, synthetic
failing tests, or invented repository states produce meaningless scores and
invalidate comparisons with external leaderboard results. Every task slug and
SHA must be verifiable against the upstream source before the corpus is frozen.
Once frozen, the corpus is immutable for the life of that eval generation.

### Mock at the right boundary

When writing tests for runner or scoring code, mock at `subprocess.run` or the
actual integration boundary (e.g. the `invoker.run_session` call that shells
out to Claude CLI), NOT at a wrapper function the runner itself owns. Mocking
the wrapper hides kwarg mismatches - a wrapper that accepts `**kwargs` silently
swallows unknown arguments, so a test that mocks it will pass even when the
real CLI invocation would fail with an unknown-flag error. This was the root
cause of the round-2 `ae-rules-injected` integration bug: `run_session` was
mocked at the high-level wrapper, `--system-prompt` was never validated, and
the bug only surfaced against the real subprocess. Rule: the mock boundary is
the last Python call before a subprocess or network call exits the process.

### Tier 3 isolation must be wired, not just built

Building `isolator.py` with a `tier_3_docker` function is necessary but not
sufficient. The runner must actually instantiate the isolator at the correct
tier and pass the container handle through the scoring pipeline. In round 1,
`isolator.py` existed and was unit-tested, but `runner.py` still defaulted to
`tier_2` for all conditions - Tier 3 was "available" but never called. The
fix: `runner.py` instantiates `isolator.tier_3_docker()` by default (gated on
`--no-tier3` flag), passes the container object to `scoring.run_held_out_tests`,
and the scorer uses it for subprocess execution. Building the component and
wiring it into the execution path are two separate acceptance criteria; both
must be verified before declaring the unit done.
